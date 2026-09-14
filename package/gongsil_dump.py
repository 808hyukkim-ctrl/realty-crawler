# -*- coding: utf-8 -*-
"""
공실클럽 샘플 수집 도구 (파서 제작용).

공실클럽은 계정이 특정 PC/IP에 묶여 있어 개발 PC에서는 로그인 안쪽 페이지를 볼 수 없다.
이 도구를 "공실클럽 로그인이 되는 PC"에서 한 번 실행하면
  - 로그인 → 목록 페이지 → 상세 페이지 HTML 을 저장하고
  - 결과를 바탕화면에 zip 하나로 묶는다.
그 zip 을 개발자에게 전달하면 정확한 파서를 만들 수 있다.

표준 라이브러리만 사용 (추가 설치 불필요).
"""
from __future__ import annotations

import http.cookiejar
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime

HOST = "https://gc2.gongsilclub.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
LOGIN_PAGE = f"{HOST}/v4/member.asp?mn=9110&wm=F160"
MEMBER_CHECK = f"{HOST}/ajax/ajax_gsc_member_check.asp"
LOGIN_POST = f"{HOST}/v4/member.asp?mn=9110&wm=P160"
MAIN_PAGE = f"{HOST}/v4/main.asp"

# 사용자가 준 목록/상세 URL (상가 검색)
SW = (
    "%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%7C%uC0C1%uAC00" + "%7C" * 63
)
LIST_URL = f"{HOST}/v4/item.asp?mn=1110&wm=F100&sw={SW}"
LIST_URL_P2 = f"{HOST}/v4/item.asp?mn=1110&wm=F100&pg=2&sw={SW}"
DETAIL_URL = f"{HOST}/v4/item.asp?mn=1110&wm=F141&pg=1&rk=1000202&sw={SW}&ItemTypeNS=%BB%F3%B0%A1"

NOT_LOGGED_IN_MARK = "로그인되어 있지 않거나"


def js_escape(s: str) -> str:
    """JS escape() 와 동일하게: A-Z a-z 0-9 @ * _ + - . / 는 유지, 나머지 %XX/%uXXXX."""
    out = []
    for ch in s:
        if ch.isascii() and (ch.isalnum() or ch in "@*_+-./"):
            out.append(ch)
        elif ord(ch) < 256:
            out.append(f"%{ord(ch):02X}")
        else:
            out.append(f"%u{ord(ch):04X}")
    return "".join(out)


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", UA), ("Accept-Language", "ko-KR,ko;q=0.9")]

    def get(self, url: str, referer: str | None = None) -> tuple[int, str]:
        req = urllib.request.Request(url)
        if referer:
            req.add_header("Referer", referer)
        with self.opener.open(req, timeout=30) as r:
            return r.status, r.read().decode("cp949", errors="replace")

    def post(self, url: str, data: dict | str, referer: str | None = None, ajax: bool = False) -> tuple[int, str]:
        body = data if isinstance(data, str) else urllib.parse.urlencode(data, encoding="cp949")
        req = urllib.request.Request(url, data=body.encode("ascii"), method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if referer:
            req.add_header("Referer", referer)
        if ajax:
            req.add_header("X-Requested-With", "XMLHttpRequest")
        with self.opener.open(req, timeout=30) as r:
            return r.status, r.read().decode("cp949", errors="replace")


def main() -> int:
    # 콘솔(cp949)에서 표현 못 하는 문자는 ?로 대체 (출력 중 예외 방지)
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    print("=" * 60)
    print(" 공실클럽 샘플 수집 도구")
    print(" (공실클럽 로그인이 되는 PC에서 실행하세요)")
    print("=" * 60)
    uid = input("공실클럽 아이디 [bridge01]: ").strip() or "bridge01"
    pwd = input("공실클럽 비밀번호: ").strip()
    if not pwd:
        print("비밀번호가 필요합니다.")
        input("Enter 를 누르면 종료합니다.")
        return 1

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    ts = datetime.now().strftime("%y%m%d_%H%M%S")
    out_dir = os.path.join(desktop, f"공실클럽_샘플_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    report: list[str] = [f"수집 시각: {datetime.now():%Y-%m-%d %H:%M:%S}", f"아이디: {uid}", ""]

    def save(name: str, html: str):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(html)

    c = Client()
    try:
        print("\n[1/6] 로그인 페이지 접속...")
        st, _ = c.get(LOGIN_PAGE)
        report.append(f"[1] 로그인 페이지 status={st}")

        print("[2/6] 계정 확인(ajax_gsc_member_check)...")
        st, txt = c.post(
            MEMBER_CHECK,
            f"USERID={js_escape(uid)}&USERPW={js_escape(pwd)}",
            referer=LOGIN_PAGE,
            ajax=True,
        )
        report.append(f"[2] member_check status={st} 응답={txt.strip()!r}")
        print(f"     응답: {txt.strip()!r}  (1|... 이면 계정 정상)")

        print("[3/6] 로그인 폼 제출(P160)...")
        form = {
            "ID": uid, "Passwd": pwd,
            "MACID": "", "CPUID": "", "HDDID": "", "OSVER": "", "COMIP": "",
            "IsApt": "0", "SaveID": "", "return_url": "", "USERID": "", "USERPW": "", "CHK_CD": "",
        }
        st, html = c.post(LOGIN_POST, form, referer=LOGIN_PAGE)
        save("1_login_response.html", html)
        # 2차 폼(form1)이 있으면 그대로 재제출 (LoginStepCurr 흐름)
        m = re.search(r'<form name="form1".*?</form>', html, re.S | re.I)
        if m:
            fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', m.group(0), re.I))
            fields.setdefault("ID", uid)
            fields.setdefault("Passwd", pwd)
            st2, html2 = c.post(LOGIN_POST, fields, referer=LOGIN_POST)
            save("1b_login_step2_response.html", html2)
            report.append(f"[3] 로그인 POST status={st} / step2 status={st2} (form1 필드 {len(fields)}개: {', '.join(sorted(fields))})")
        else:
            report.append(f"[3] 로그인 POST status={st} (form1 없음)")
        cookies = "; ".join(f"{k.name}={k.value[:30]}" for k in c.cj)
        report.append(f"    쿠키: {cookies}")

        print("[4/6] 메인 페이지(로그인 상태 확인)...")
        st, html = c.get(MAIN_PAGE)
        save("2_main.html", html)
        has_logout = "LogOutGongsilclub()" in html and 'onclick="LogOutGongsilclub' in html
        report.append(f"[4] 메인 status={st} size={len(html)} 로그아웃버튼={'있음(로그인됨)' if has_logout else '없음'}")

        print("[5/6] 매물 목록 페이지...")
        st, html = c.get(LIST_URL, referer=MAIN_PAGE)
        save("3_list_p1.html", html)
        rks = sorted(set(re.findall(r"rk=(\d+)", html)))
        not_logged = NOT_LOGGED_IN_MARK in html
        report.append(f"[5] 목록 p1 status={st} size={len(html)} 매물링크(rk)={len(rks)}개 비로그인표시={'예' if not_logged else '아니오'}")
        print(f"     매물 링크 {len(rks)}개 발견" + (" - 로그인 안 된 상태로 보입니다!" if not rks else ""))
        if rks:
            st, html = c.get(LIST_URL_P2, referer=LIST_URL)
            save("3_list_p2.html", html)
            report.append(f"    목록 p2 status={st} size={len(html)} rk={len(set(re.findall(r'rk=(\d+)', html)))}개")

        print("[6/6] 매물 상세 페이지...")
        detail_url = DETAIL_URL
        if rks and "1000202" not in rks:
            detail_url = f"{HOST}/v4/item.asp?mn=1110&wm=F141&pg=1&rk={rks[0]}&sw={SW}&ItemTypeNS=%BB%F3%B0%A1"
        st, html = c.get(detail_url, referer=LIST_URL)
        save("4_detail.html", html)
        not_logged = NOT_LOGGED_IN_MARK in html
        report.append(f"[6] 상세 status={st} size={len(html)} url={detail_url}")
        report.append(f"    비로그인표시={'예' if not_logged else '아니오'}")
        if rks and len(rks) > 1:
            st, html = c.get(
                f"{HOST}/v4/item.asp?mn=1110&wm=F141&pg=1&rk={rks[1]}&sw={SW}&ItemTypeNS=%BB%F3%B0%A1",
                referer=LIST_URL,
            )
            save("4_detail_2.html", html)
            report.append(f"    상세2 status={st} size={len(html)} rk={rks[1]}")

        report.append("")
        report.append("판정: " + ("로그인 성공 - 파서 제작 가능" if rks and not not_logged else "로그인 실패 또는 매물 없음 - 개발자에게 이 파일 그대로 전달"))
    except Exception as e:  # noqa: BLE001
        report.append(f"\n오류: {type(e).__name__}: {e}")
        print(f"\n오류 발생: {e}")

    with open(os.path.join(out_dir, "0_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    zip_path = os.path.join(desktop, f"공실클럽_샘플_{ts}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(out_dir)):
            z.write(os.path.join(out_dir, name), name)

    print("\n" + "-" * 60)
    print("\n".join(report))
    print("-" * 60)
    print(f"\n완료. 이 파일을 개발자에게 전달하세요:\n  {zip_path}")
    input("\nEnter 를 누르면 종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

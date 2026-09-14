import requests as req 
from tls_client import Session 
import json 
import os 
from datetime import datetime as dt, timedelta as td 
from bs4 import BeautifulSoup as bs 

sess = Session()
sess.headers.update({
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IlJFQUxFU1RBVEUiLCJpYXQiOjE3NTU4NjE2MDIsImV4cCI6MTc1NTg3MjQwMn0.oUESmR0PhLfqPu50Dp0Ksd8hH6CbN69Kgy1AtKAJBkA",
    "Connection": "keep-alive",
    "Cookie": "NNB=DHVGK5NIFRZGQ; BUC=dQnzU4cEAFITbLHCXucm96M1Hygq1eXI9lNBTGomvQ8=; NAC=bf7HCYhdY1viB; nstore_session=GhC7pWraNQqUi1r/3Cat+iHt; nstore_pagesession=jcNSelqqFq2n0wsMS4d-275984; ASID=d261344a00000198112a58d000000023; nhn.realestate.article.rlet_type_cd=A01; nhn.realestate.article.trade_type_cd=\"\"; nhn.realestate.article.ipaddress_city=4100000000; _fwb=2477cFBKnotdBO5kFtJXAxb.1755860647279; landHomeFlashUseYn=Y; NACT=1; SRT30=1755860649; REALESTATE=Fri%20Aug%2022%202025%2020%3A20%3A02%20GMT%2B0900%20(Korean%20Standard%20Time); PROP_TEST_KEY=1755861602330.91922a3ba1b2bed031aac365bc7783fb4ad34c557cfec7fe9de50e9bbd33395f; PROP_TEST_ID=13ef4231cf828a73659d00b359317c1ed14816b42c7301637b8f1b90db90f7df; _fwb=2477cFBKnotdBO5kFtJXAxb.1755860647279; SRT5=1755861459",
    "Host": "new.land.naver.com",
    "Referer": "https://new.land.naver.com/rooms?ms=37.362105,127.1040745,17&a=APT:OPST:ABYG:OBYG:GM:OR:DDDGG:JWJT:SGJT:HOJT:VL&e=RETAIL&aa=SMALLSPCRENT",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "TE": "trailers",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:142.0) Gecko/20100101 Firefox/142.0"
})


def convert_price(price):
    if not price or price == 0:
        return None 
    
    if isinstance(price, str) and "억" in price:
        price = price.replace("억", "").replace(" ","").replace(",","")
        price = int(price)

    return "{:,}".format(int(int(price) * 10000))

def convert_date(date):

    if not date:
        return date 
    
    if len(date) == 6:
        new_date = date[:4] + "-" + date[4:]
    elif len(date) == 8:
        new_date = date[:4] + "-" + date[4:6] + "-" + date[6:]
    else:
        return date 

    return new_date 
    
def get_gongsi(landprice_res):
    landprice_total = landprice_res.json().get("landPriceTotal","")
    if landprice_total:
        landprice_floors = landprice_total.get("landPriceFloors","")
        if landprice_floors and isinstance(landprice_floors, list) and len(landprice_floors) > 0:
            for landprice_floor in landprice_floors:
                landprices = landprice_floor.get("landPrices", "")
                if landprices and isinstance(landprices, list) and len(landprices) > 0:
                    for landprice in landprices:
                        if landprice.get("stdYmd"):
                            gongsi_std_ymd = convert_date(str(landprice.get("stdYmd")))
                            return gongsi_std_ymd
                        
    return None 

def find_key_in_nested_dict(d, target_key):

    if isinstance(d, dict): 
        for key, value in d.items():
            if key == target_key:
                return value
            if isinstance(value, dict):
                result = find_key_in_nested_dict(value, target_key)
                if result is not None: 
                    return result
            elif isinstance(value, list): 
                for item in value:
                    if isinstance(item, dict): 
                        result = find_key_in_nested_dict(item, target_key)
                        if result is not None:
                            return result
    return None 


def find_keys_with_value(data, target_value):

    if isinstance(data, dict):
    
        for key, value in data.items():
 
            if isinstance(value, dict):
                result = find_keys_with_value(value, target_value)
                if result:
                    return result
            
            else:
                if value == target_value:
                    return key 

def get_r(si, gu, dong):

    if gu == "구 선택":
        first_gu_key = list(rls[si].keys())[0]
        first_dong_key = list(rls[si][first_gu_key].keys())[0]
        print(rls[si][first_gu_key][first_dong_key][:2].ljust(10, "0"))
        return [si, None, None, rls[si][first_gu_key][first_dong_key][:2].ljust(10, "0")]
    
    elif dong == "동 선택":
        first_dong_key = list(rls[si][gu].keys())[0]
        return [si, gu, None, rls[si][gu][first_dong_key][:5].ljust(10, "0")]

    return [si, gu, dong, rls[si][gu][dong]]

def prepare_params(params):
    prepared = {}
    for key, value in params.items():
        if value is None:
            prepared[key] = ''
        elif isinstance(value, bool):
            prepared[key] = 'true' if value else 'false'
        elif isinstance(value, (int, float)):
            prepared[key] = str(value)
        else:
            prepared[key] = str(value)
    return prepared

def get_cls(*r, realestate_type="APT:ABYG:JGC:PRE", tag="::::::::", trade_type=None, min_deal_price=None, max_deal_price=None,
            min_warranty_price=None, max_warranty_price=None, min_rent_price=None, max_rent_price=None,
            min_area=None, max_area=None, max_days_from_now=None):

    si, gu, dong, r_no = r 

    cls = []

    if "IA01:IA02:IC01:IC02:IA04:IC03" != realestate_type:
        cls_url = "https://new.land.naver.com/api/articles"

        if "A1" in trade_type and ("B1" in trade_type or "B2" in trade_type):
            min_price = min(min_deal_price if min_deal_price else 0, min_warranty_price if min_warranty_price else 0)
            max_price = max(max_deal_price if max_deal_price else 900000000, max_warranty_price if max_warranty_price else 900000000)
        elif "A1" in trade_type:
            min_price = min_deal_price if min_deal_price else 0
            max_price = max_deal_price if max_deal_price else 900000000
        elif "B1" in trade_type or "B2" in trade_type:
            min_price = min_warranty_price if min_warranty_price else 0
            max_price = max_warranty_price if max_warranty_price else 900000000
        else:
            min_price = 0
            max_price = 900000000

        cls_params = {
            "cortarNo": r_no,
            "order": "rank",
            "realEstateType": realestate_type,
            "tradeType": trade_type,
            "tag": tag,
            "rentPriceMin": min_rent_price if min_rent_price else 0,
            "rentPriceMax": max_rent_price if max_rent_price else 900000000,
            "priceMin": min_price,
            "priceMax": max_price,
            "areaMin": min_area if min_area else 0,
            "areaMax": max_area if max_area else 900000000,
            "oldBuildYears": "",
            "recentlyBuildYears": "",
            "minHouseHoldCount": "",
            "maxHouseHoldCount": "",
            "showArticle": False,
            "sameAddressGroup": False,
            "minMaintenanceCost": "",
            "maxMaintenanceCost": "",
            "priceType": "RETAIL",
            "directions": "",
            "page": 1,
            "articleState": ""
        }
        print(cls_params)

        is_more_data = True 
        page = 1
        article_no_list = []

        while is_more_data:

            cls_params["page"] = page 

            cls_res = sess.get(cls_url, params=cls_params)
            print(cls_res, page)
            is_more_data = cls_res.json().get("isMoreData")

            article_list = cls_res.json().get("articleList")

            for article in article_list:
    
                article_no = article.get("articleNo")

                article_confirm_date = article.get("articleConfirmYmd", "")
                if max_days_from_now and article_confirm_date:
                    article_confirm_dt = dt.strptime(article_confirm_date, "%Y%m%d")
                    if article_confirm_dt < dt.now() - td(days=max_days_from_now):
                        continue 

                if article_no and article_no not in article_no_list:
                    cls.append({
                        "si" : si, 
                        "gu" : gu, 
                        "dong" : dong, 
                        "complex_name" : article.get("articleName"),
                        "complex_no" : article_no,
                        "realestate_type_name" : article.get("realEstateTypeName"),
                        "realestate_type" : article.get("realEstateTypeCode", "")  
                    })

                article_no_list.append(article_no)

            page += 1

    if "IA01:IA02:IC01:IC02:IA04:IC03" in realestate_type:

        pre_url = "https://isale.land.naver.com/iSale/AjaxContent/"
        pre_data = {
            "sy_ajax_content": "SYAreaComplexList",
            "sy_sido": si,
            "sy_gugun": gu, 
            "sy_dong": dong,
            "bclass": "IA01:IA02:IC01:IC02:IA04:IC03",
            "sy_sort": 0
        }
        pre_res = sess.post(pre_url, data=pre_data)
        print(pre_res)
        soup = bs(pre_res.text, "lxml-xml")
        # print(soup)
        try:
            complex_data = soup.select_one("sycomplexdata")
            if complex_data:
                ext_data = complex_data.text.split("CDATA[", 1)[1].split("]]>", 1)[0]
                ext_data = json.loads(ext_data)
                ext_data = ext_data.get("Data")
            else:
                complex_data = soup.select_one("SYComplexData")
                ext_data = json.loads(complex_data.text).get("Data")
                
            build_dtl_cd_list = [[e.get("build_dtl_cd"), e.get("supp_cd")] for e in ext_data]

            import xmltodict 

            for build_dtl_cd in build_dtl_cd_list:

                det_data = {
                    "sy_ajax_content": "SYComplexInfo",
                    "build_dtl_cd": build_dtl_cd[0],
                    "supp_cd": build_dtl_cd[1],
                    "SYMap": None,
                    "a": "IA01:IA02:IC01:IC02:IA04:IC03"
                }

                try:
                    det_res = sess.post(pre_url, data=det_data)
                    print(det_res)

                    xml_dict = xmltodict.parse(det_res.text)
                    # print(xml_dict)
                    view_content = xml_dict["channel"]["SYViewContent"]
                    view_content_soup = bs(view_content, "html.parser")

                    complex_content = xml_dict["channel"]["SYComplexContent"]
                    complex_content_soup = bs(complex_content, "html.parser")
                    info_table = complex_content_soup.select_one("table.InfoTableWrap tbody")

                    try:
                        name = view_content_soup.select_one("h3.Title").text
                    except: name = None  

                    try: 
                        total_floor = view_content_soup.find(string=lambda text: "층" in text).text.replace("층","")
                    except: total_floor = None  

                    try:
                        deal_price = ((convert_price(view_content_soup.select_one("dd.Data").text.split("~")[0].strip())) + " ~ " + 
                                        (convert_price(view_content_soup.select_one("dd.Data").text.split("~")[1].strip())))
                    except: deal_price = None  

                    try:
                        nanbang = complex_content_soup.find("th", string="난방방식").find_parent().select_one("td").text
                    except: nanbang = None 

                    try: 
                        movein_possible_ymd = convert_date(view_content_soup.select_one("dd.Date").text.split("입주")[1].replace(".","").strip())
                    except: movein_possible_ymd = None

                    try: 
                        detail_addr = " ".join(complex_content_soup.find("th", string="분양주소").find_parent().select_one("td").text.split(" ")[2:])
                    except: detail_addr = None 

                    try:
                        construction_company_name = complex_content_soup.find("th", string="건설사").find_parent().select_one("td").text
                    except : construction_company_name = None 

                    try:
                        saede_num = complex_content_soup.find("th", string="단지규모").find_parent().select_one("td").text.split("세대", 1)[0].split(" ")[-1]
                    except: saede_num = None 

                    try: 
                        dong_num = complex_content_soup.find("th", string="단지규모").find_parent().select_one("td").text.split("개동", 1)[0].split(" ", -1)[1]
                    except: dong_num = None 

                    try:
                        park_count = complex_content_soup.find("th", string="주차대수").find_parent().select_one("td").text.split("대", 1)[0]
                    except: park_count = None 

                    # print(json.dumps(xml_dict, indent=4))
                    try:
                        sy_json = json.loads(xml_dict["channel"]["SYJson"])
                    except: pass 

                    try:
                        if not deal_price:
                            deal_price = sy_json.get("price")
                            if deal_price:
                                deal_price = ((convert_price(deal_price.replace(",","").split("~")[0].strip())) + " ~ " + 
                                            (convert_price(deal_price.replace(",","").split("~")[1].strip())))
                    except: pass 
                    try:
                        if not saede_num:
                            saede_num = sy_json.get("total_house_cnt")
                            if saede_num:
                                saede_num = saede_num.split("총")[1].split("세대").strip()
                    except: pass 
                    try: 
                        if not movein_possible_ymd:
                            movein_possible_ymd = sy_json.get("move_in_date")
                            if movein_possible_ymd:
                                movein_possible_ymd = convert_date(movein_possible_ymd)
                    except: pass 

                    in_data = {
                            "addr_si" : si, 
                            "addr_gu" : gu,
                            "addr_dong" : dong,
                            "url_with_no" : f"https://isale.land.naver.com/iSale/Map/#SYDetail?build_dtl_cd={build_dtl_cd[0]}&supp_cd={build_dtl_cd[1]}&a=IA01:IA02:IC01:IC02:IA04:IC03",
                            "expose_start_ymd": None,
                            "verification_type_name": None,
                            "realestate_type": "분양중/예정",
                            "trade_type": None,
                            "name": name, 
                            "dong": None,
                            "area1": None,
                            "area2": None,
                            "arch_area": None,
                            "exclusive_rate": None,
                            "yj_rate": None,
                            "gp_rate": None,
                            "floor": None,
                            "total_floor": total_floor,
                            "direction": None,
                            "deal_price": deal_price,
                            "rent_price": None,
                            "price_by_space": None,
                            "gongsi_std_ymd": None,
                            "gongsi_min_price": None,
                            "gongsi_max_price": None,
                            "right_price": None,
                            "finance_price": None,
                            "all_warrant_price": None,
                            "all_rent_price": None,
                            "premium_price": None,
                            "biz_step": None,
                            "usage_district": None,
                            "management_cost": None,
                            "room_count": None,
                            "bathroom_count": None,
                            "nanbang": nanbang if nanbang != "-" else nanbang,
                            "current_usage": None,
                            "recommend_usage": None,
                            "building_usage": None,
                            "jisang_jiha_floor": None,
                            "movein_possible_ymd": movein_possible_ymd,
                            "simple_description": None,
                            "detail_description": None,
                            "sojaeji": f"{si} {gu}",
                            "addr": None,
                            "detail_addr": detail_addr,
                            "lat_long": None,
                            "construction_company_name": construction_company_name,
                            "apt_use_approve_ymd" : None,
                            "saede_num": saede_num,
                            "dong_num": dong_num,
                            "park_count": park_count,
                            "agent_num": None,
                            "agent_name": None,
                            "agent_man_name": None,
                            "agent_addr": None,
                            "agent_no": None,
                            "agent_tel": None,
                            "agent_phone": None
                        }
                    
                    cls.append({
                        "si" : si, 
                        "gu" : gu, 
                        "dong" : dong, 
                        "complex_name" : name,
                        "complex_no" : None,
                        "realestate_type_name" : "분양중/예정",
                        "realestate_type" : "IA01:IA02:IC01:IC02:IA04:IC03",
                        "in_data" : in_data 
                    })
                except: 
                    continue 
        except: pass 

    return cls 


__all__ = ['convert_price', 'convert_date']


url_realestate_type_dict = {
    "APT" : "complexes",
    "JGC" : "complexes",
    "PRE" : "complexes",
    "OBYG" : "complexes",
    "ABYG" : "complexes",
    "JGB" : "complexes",
    "OPST" : "complexes",
    "VL" : "houses",
    "DDDGG" : "houses",
    "JWJT" : "houses",
    "SGJT" : "houses",
    "HOJT" : "houses",
    "OR" : "rooms",
    "SG" : "offices",
    "SMS" : "offices",
    "APTHGJ" : "offices",
    "GM" : "offices",
    "TJ" : "offices",
    "GJCG" : "offices"
}

direction_dict = {
    "EE" : "동향",
    "WW" : "서향",
    "SS" : "남향",
    "NN" : "북향",
    "EN" : "북동향",
    "ES" : "남동향",
    "WN" : "북서향 ",
    "WS" : "남서향"
}

biz_step_types = {
    "01": "기본계획수립",
    "02": "안전진단",
    "03": "구역지정",
    "04": "추진위승인",
    "05": "조합설립인가",
    "06": "사업시행인가",
    "07": "관리처분인가",
    "08": "이주 및 철거",
    "09": "착공 및 분양",
    10: "준공",
    11: "이전고지"
}

def get_complex_info(c, realestate_type="APT:ABYG:JGC:PRE", tag="::::::::", trade_type=None, min_deal_price=None, max_deal_price=None,
            min_warranty_price=None, max_warranty_price=None, min_rent_price=None, max_rent_price=None,
            min_area=None, max_area=None):

    c_no = c["complex_no"]
    realestate_type = c["realestate_type"]
    print(c_no)


    c_list_url = f"https://new.land.naver.com/api/articles/complex/{c_no}"

    page = 1

    c_list_params = {
        "realEstateType": realestate_type,
        "tradeType": trade_type,
        "tag": tag,
        "rentPriceMin": min_rent_price if min_rent_price else 0,
        "rentPriceMax": max_rent_price if max_rent_price else 900000000,
        "priceMin": min_deal_price if min_deal_price else 0,
        "priceMax": max_deal_price if max_deal_price else 900000000,
        "areaMin": min_area if min_area else 0,
        "areaMax": max_area if max_area else 900000000,
        "oldBuildYears": "",
        "recentlyBuildYears": "",
        "minHouseHoldCount": "",
        "maxHouseHoldCount": "",
        "showArticle": False,
        "sameAddressGroup": False,
        "minMaintenanceCost": "",
        "maxMaintenanceCost": "",
        "priceType": "RETAIL",
        "directions": "",
        # "page": page,
        "complexNo": c_no,
        "buildingNos": "",
        "areaNos": "",
        "type": "list",
        "order": "rank"
    }

    is_more_data = True 

    data = []

    if c_no:

        new_c_no_list = [c_no]

        try:
            while is_more_data:

                c_list_params["page"] = page 

                print(f"{page}페이지 진행중...")

                c_list_res = sess.get(c_list_url, params=c_list_params)
                print(c_list_res)
                # print(c_list_res.text)
                is_more_data = c_list_res.json().get("isMoreData")
                c_list = c_list_res.json().get("articleList")

                article_no_list = [c.get("articleNo") for c in c_list if c.get("articleNo")]

                new_c_no_list.extend(article_no_list)

                page += 1
        except:
            pass 

        for new_c_no in new_c_no_list:

            c_info_url = f"https://new.land.naver.com/api/articles/{new_c_no}?complexNo="
            
            try:
                c_info_res = sess.get(c_info_url)
                print(c_info_res)
                c_info = c_info_res.json()
                with open("c_info.json", "w", encoding="utf-8") as f:
                    json.dump(c_info, f, ensure_ascii=False, indent=4)

                # article_no = None 
                addr_si = None 
                addr_gu = None
                addr_dong = None
                expose_start_ymd = None 
                verification_type_name = None 
                realestate_type = None 
                trade_type = None 
                name = c["complex_name"] 
                dong = None 
                area1 = None 
                area2 = None 
                arch_area = None 
                exclusive_rate = None 
                yj_rate = None 
                gp_rate = None 
                direction = None 
                floor = None 
                total_floor = None 
                deal_price = None 
                rent_price = None 
                price_by_space = None 
                gongsi_std_ymd = None  #
                gongsi_min_price = None # 
                gongsi_max_price = None #
                right_price = None 
                finance_price = None 
                all_warrant_price = None 
                all_rent_price = None 
                premium_price = None 
                biz_step = None 
                usage_district = None # 용도지역 
                management_cost = None 
                room_count = None 
                bathroom_count = None 
                nanbang = None
                current_usage = None
                recommend_usage = None
                building_usage = None # 건축물용도 
                jisang_jiha_floor = None 
                movein_possible_ymd = None
                simple_description = None 
                detail_description = None
                sojaeji = None 
                addr = None 
                detail_addr = None 
                lat_long = None 
                construction_company_name = None
                saede_num = None
                dong_num = None
                park_count = None
                agent_num = None  # 중개사수
                agent_name = None 
                agent_man_name = None 
                agent_addr = None 
                agent_no = None 
                agent_tel = None # 중개사 전화 
                agent_phone = None # 중개사 휴대폰

                article_detail = c_info.get("articleDetail")
                # article_no = article_detail.get("articleNo", "") # 

                if not article_detail: continue 

                hscp_no = article_detail.get("hscpNo", "")
                dong_no = article_detail.get("buildNo", "")

                detail_addr_url = f"https://new.land.naver.com/api/complexes/{hscp_no}?sameAddressGroup=false"
                try:
                    detail_addr_res = sess.get(detail_addr_url)
                    if detail_addr_res.status_code != 200:
                        raise Exception
                    print(detail_addr_res)
                    # print(detail_addr_res.text)
                    c_detail = detail_addr_res.json().get("complexDetail", "")
                    if c_detail:
                        detail_addr = f'{c_detail.get("address").split(" ")[-1]} {c_detail.get("detailAddress")}'
                        yj_rate = c_detail.get("batlRatio", "")
                        gp_rate = c_detail.get("btlRatio", "")
                except: pass 

                landprice_url = f"https://new.land.naver.com/api/complexes/{hscp_no}/buildings/landprice"
                landprice_params = {
                    "dongNo" : dong_no, 
                    "complexNo" : hscp_no 
                }
                try:
                    landprice_res = sess.get(landprice_url, params=landprice_params)
                    if landprice_res.status_code != 200:
                        raise Exception 
                    print(landprice_res)
                    gongsi_std_ymd = get_gongsi(landprice_res)
                    landprice_color_summary = landprice_res.json().get("landPriceColorSummary", "")
                    if landprice_color_summary:
                        gongsi_min_price = landprice_color_summary.get("minLandPrice", "")
                        gongsi_min_price = "{:,}".format(gongsi_min_price)
                        gongsi_max_price = landprice_color_summary.get("maxLandPrice", "")
                        gongsi_max_price = "{:,}".format(gongsi_max_price)
                except: pass 

                addr_si = article_detail.get("cityName", "")
                addr_gu = article_detail.get("divisionName", "")
                addr_dong = article_detail.get("sectionName", "")
                sojaeji = article_detail.get("exposureAddress", "")
                if not sojaeji:
                    sojaeji = f"{addr_si} {addr_gu}".strip()
                expose_start_ymd = article_detail.get("exposeStartYMD", "")
                expose_start_ymd = convert_date(expose_start_ymd)

                verification_type_name = article_detail.get("verificationTypeName", "")
                realestate_type = article_detail.get("realestateTypeName", "")
                realestate_type_code = article_detail.get("realestateTypeCode", "")
                # building_type = building_types[building_type_code]
                trade_type_code = article_detail.get("tradeTypeCode", "")
                if trade_type and trade_type_code and trade_type_code not in trade_type:
                    continue 
                trade_type = article_detail.get("tradeTypeName", "")
                # name = article_detail.get("aptName", "")
                print(name)
                dong = article_detail.get("buildingName", "")
                article_addition = c_info.get("articleAddition")
                area1 = article_addition.get("area1", "") # 공급,계약,대지 
                area2 = article_addition.get("area2", "") # 전용,연
                if area1 and (min_area and area1 < min_area) or (max_area and area1 > max_area):
                    continue 
                article_space = c_info.get("articleSpace", "")
                arch_area = article_space.get("buildingSpace", "") if article_space else None 
                arch_area = int(float(arch_area)) if arch_area else arch_area # 건면적 
                exclusive_rate = article_space.get("exclusiveRate", "") if article_space else None # 전용률
                # if area1 and area2:
                #     yj_rate = int(area2 / area1) # 용적률
                article_redevelop = c_info.get("articleRedevelop", "")
                if not yj_rate:
                    yj_rate = find_key_in_nested_dict(c_info, "floorAreaRatio")
                if not yj_rate or yj_rate == "-" or realestate_type == "전원주택":
                    yj_rate = find_key_in_nested_dict(c_info, "vlRat")
                if not gp_rate: 
                    gp_rate = find_key_in_nested_dict(c_info, "buildingCoverageRatio")
                if not gp_rate or gp_rate == "-" or realestate_type == "전원주택":
                    gp_rate = find_key_in_nested_dict(c_info, "bcRat")
                # yj_rate = article_redevelop.get("floorAreaRatio", "") if article_redevelop else None # 용적률
                # gp_rate = article_redevelop.get("buildingCoverageRatio", "") if article_redevelop else None # 건폐율 

                direction = article_addition.get("direction", "")
                floor_info = article_addition.get("floorInfo", "")
                if floor_info:
                    floor = floor_info.split("/")[0].strip()
                    total_floor = floor_info.split("/")[1].strip()

                article_price = c_info.get("articlePrice")
                if trade_type_code == "A1":
                    deal_price = article_price.get('dealPrice', "")
                    if (deal_price and (min_deal_price and deal_price < min_deal_price)
                    or (max_deal_price and deal_price > max_deal_price)):
                        continue 

                elif trade_type_code == "B1" or trade_type_code == "B2" or trade_type_code == "B3":
                    deal_price = article_price.get("warrantPrice", "")
                    if (deal_price and (min_warranty_price and deal_price < min_warranty_price)
                    or (max_warranty_price and deal_price > max_warranty_price)):
                        continue 
                deal_price = convert_price(deal_price)
                price_by_space = c_info.get("priceBySpace", "")
                price_by_space = convert_price(price_by_space)

                rent_price = article_price.get("rentPrice", "")
                if (rent_price and (min_rent_price and rent_price < min_rent_price)
                        or (max_rent_price and rent_price > max_rent_price)):
                    continue 
                rent_price = convert_price(rent_price)
                right_price = article_price.get("rightPrice") # 권리금 
                right_price = convert_price(right_price)
                finance_price = article_price.get("financePrice", "") # 융자금
                finance_price = convert_price(finance_price)
                # all_warrant_price = article_price.get("allWarrantPrice", "") # 기보증금 
                # if (all_warrant_price and (min_warranty_price and all_warrant_price < min_warranty_price)
                #         or (max_warranty_price and all_warrant_price > max_warranty_price)):
                #     continue 
                # all_warrant_price = convert_price(all_warrant_price)
                # all_rent_price = article_price.get("allRentPrice", "") # 기월세 
                # all_rent_price = convert_price(all_rent_price)
                premium_price = article_price.get("premiumPrice", "") 
                premium_price = convert_price(premium_price)
                biz_step = find_key_in_nested_dict(c_info, "bizStepDescription") # 사업시행단계

                article_facility = c_info.get("articleFacility", "")

                management_cost = article_detail.get("monthlyManagementCost", "") # 관리비 

                admin_cost_info = c_info.get("administrationCostInfo", "")
                if not management_cost and admin_cost_info:
                    etc_fee_details = admin_cost_info.get("etcFeeDetails", "")
                    if etc_fee_details:
                        management_cost = etc_fee_details.get("etcFeeAmount", "") if admin_cost_info else None 
                if not management_cost and admin_cost_info:
                    fixed_fee_details = admin_cost_info.get("fixedFeeDetails", "")
                    if fixed_fee_details:
                        management_cost = sum([f.get("amount") for f in fixed_fee_details if f.get("amount")])

                if management_cost:
                    management_cost = "{:,}".format(management_cost)

                room_count = article_detail.get("roomCount", "") 
                bathroom_count = article_detail.get("bathroomCount", "")
                nanbang = (f'{article_facility.get("heatMethodTypeName", "")}/{article_facility.get("heatFuelTypeName", "")}'
                        if article_facility and article_facility.get("heatMethodTypeName", "") else None)
                if nanbang is None:
                    nanbang = (f'{article_detail.get("aptHeatMethodTypeName", "")}/{article_detail.get("aptHeatFuelTypeName", "")}'
                        if article_detail and article_detail.get("aptHeatMethodTypeName", "") else None)
                current_usage = article_detail.get("currentUsage", "") # 현재업종 
                recommend_usage = article_detail.get("recommendUsage", "") # 추천업종 

                article_br = c_info.get("articleBuildingRegister", "")

                article_floor = c_info.get("articleFloor", "")
                jisang_floor = article_floor.get("uppergroundFloorCount", "") if article_floor else None 
                jiha_floor = article_floor.get("undergroundFloorCount", "") if article_floor else None 
                if jisang_floor and jiha_floor and not (jisang_floor == "-" and jiha_floor == "-") :
                    jisang_jiha_floor = f"{jisang_floor}/{jiha_floor}"

                movein_possible_ymd = article_detail.get("moveInPossibleYmd", "") # 입주가능일
                if not movein_possible_ymd:
                    movein_possible_ymd = find_key_in_nested_dict(c_info, "moveInTypeName")
                try:
                    movein_possible_ymd = convert_date(movein_possible_ymd)
                except: pass 
                simple_description = article_detail.get("articleFeatureDescription", "") # 간략설명
                detail_description = article_detail.get("detailDescription", "") # 설명 
                # sojaeji = f"{article_detail.get("cityName", "")} {article_detail.get("divisionName", "")}".strip() # 소재지
                # sojaeji = f"{c["si"]} {c["gu"]}"
                lat_long = f'{article_detail.get("latitude", "")},{article_detail.get("longitude", "")}'
                construction_company_name = find_key_in_nested_dict(c_info, "aptConstructionCompanyName")
                if not construction_company_name:
                    construction_company_name = find_key_in_nested_dict(c_info, "constructorName")
                apt_use_approve_ymd = article_detail.get("aptUseApproveYmd", "") # 사용승인일
                if not apt_use_approve_ymd:
                    apt_use_approve_ymd = article_facility.get("buildingUseAprvYmd", "") if article_facility else None 
                apt_use_approve_ymd = convert_date(apt_use_approve_ymd)
                saede_num = article_detail.get("aptHouseholdCount", "")
                if not saede_num:
                    saede_num = find_key_in_nested_dict(c_info, "householdCount")
                if not saede_num:
                    saede_num = find_key_in_nested_dict(c_info, "allHoCnt")
                dong_num = article_detail.get("totalDongCount", "")
                # is_parking_possible = find_key_in_nested_dict("parkingPossibleYN", "")
                park_count = article_br.get("totalParkingCnt", "") if article_br else article_detail.get("aptParkingCount", "")

                # 건축물대장정보 
                # article_building_register = c_info.get("articleBuildingRegister", "")
                # if article_building_register:
                #    # building_usage = 
                #     saede_num = article_building_register.get("allHoCnt", saede_num)
                #     if not saede_num:
                #        saede_num = article_building_register.get("fmlyCnt", saede_num)
                #     usage_district = article_building_register.get("jiyukNm", usage_district)
                #     apt_use_approve_ymd = article_building_register.get("useAprDay", apt_use_approve_ymd)
                #     if apt_use_approve_ymd:
                #         apt_use_approve_ymd = apt_use_approve_ymd.replace(".","-")
                #     try:
                #         area1 = article_building_register.get("platArea", area1)
                #         if area1: area1 = int(float(area1))
                #     except: pass 
                #     try:
                #         area2 = article_building_register.get("vlRatEstmTotArea", area2)
                #         if area2: area2 = int(float(area2))
                #     except: pass
                #     yj_rate =  article_building_register.get("vlRat", yj_rate)
                #     gp_rate = article_building_register.get("bcRat", gp_rate)
                #     park_count = article_building_register.get("totalParkingCnt", "")


                pbs_url = f"https://fin.land.naver.com/articles/{new_c_no}"
                try:
                    pbs_res = sess.get(pbs_url)
                    if pbs_res.status_code != 200:
                        raise Exception 
                    print(pbs_res.status_code)

                    pbs_soup = bs(pbs_res.text, "html.parser")

                    if not price_by_space:
                        try:
                            price_by_space = pbs_soup.select_one("span.ArticleSummary_info-size___Ut9Q")
                            if price_by_space:
                                price_by_space = price_by_space.text.split("만원")[0].replace("억 ", "")
                        except: pass 

                    try:
                        scripts = pbs_soup.select("script")
                        target_script = None 
                        for script in scripts:
                            if script.get("id") == "__NEXT_DATA__":
                                target_script = script
                                break 

                        info_json = json.loads(target_script.string)

                        if not yj_rate or yj_rate == "-" or realestate_type == "재개발":
                            try:
                                yj_rate = find_key_in_nested_dict(info_json, "floorAreaRatio")
                                if "재개발" == realestate_type or not yj_rate:
                                    building_ratio_info = find_key_in_nested_dict(info_json, "buildingRatioInfo")
                                    if building_ratio_info:
                                        yj_rate = building_ratio_info.get("floorAreaRatio", "")
                                if yj_rate: yj_rate = int(yj_rate)
                            except: pass 
                        if not gp_rate or gp_rate == "-" or realestate_type == "재개발":
                            try:
                                gp_rate = find_key_in_nested_dict(info_json, "buildingCoverageRatio")
                                if "재개발" == realestate_type or not gp_rate:
                                    building_ratio_info = find_key_in_nested_dict(info_json, "buildingRatioInfo")
                                    if building_ratio_info:
                                        gp_rate = building_ratio_info.get("buildingCoverageRatio", "")
                                if gp_rate: gp_rate = int(gp_rate)
                            except: pass 
                        if not rent_price:
                            try:
                                rent_price = find_key_in_nested_dict(info_json, "rentAmount")
                                if rent_price: rent_price = "{:,}".format(rent_price)
                            except: pass 
                        if not deal_price and trade_type_code == "B1":
                            try:
                                deal_price = find_key_in_nested_dict(info_json, "warrantyAmount")
                                if deal_price: deal_price = "{:,}".format(deal_price)
                            except: pass 
                        if not all_warrant_price:
                            try:
                                all_warrant_price = find_key_in_nested_dict(info_json, "previousDeposit")
                                if all_warrant_price: all_warrant_price = "{:,}".format(all_warrant_price)
                            except: pass 
                        if not all_rent_price:
                            try:
                                all_rent_price = find_key_in_nested_dict(info_json, "previousMonthlyRent")
                                if all_rent_price: all_rent_price = "{:,}".format(all_rent_price)
                            except: pass 
                        if not direction:
                            try:
                                direction = find_key_in_nested_dict(info_json, "direction")
                                if direction: direction = direction_dict[direction]
                            except: pass 
                        if not building_usage:
                            try:
                                building_usage = find_key_in_nested_dict(info_json, "buildingUse")
                                if not building_usage:
                                    building_usage = find_key_in_nested_dict(info_json, "buildingPrincipalUse")
                            except: pass 
                        if not usage_district:
                            try:
                                usage_district = find_key_in_nested_dict(info_json, "areaUsage")
                            except: pass
                        if not usage_district or not saede_num: 
                            if not usage_district:
                                pnu = find_key_in_nested_dict(info_json, "pnu")
                                if pnu:
                                    pnu_res = sess.get(f"https://fin.land.naver.com/front-api/v1/complex/buildingRegistration?pnu={pnu}")
                                    if pnu_res.status_code != 200: raise Exception 
                                    print(pnu_res)
                                    if not usage_district:
                                        try:
                                            special_purpose_info = find_key_in_nested_dict(pnu_res.json(), "specialPurposeInfo")
                                            if special_purpose_info:
                                                    usage_district = special_purpose_info.get("area").get("purpose")
                                        except: pass 
                                    if not saede_num:
                                        try:
                                            saede_num = find_key_in_nested_dict(pnu_res.json(), "hoNumber")
                                        except: pass 
                                        if not saede_num:
                                            try: 
                                                saede_num = find_key_in_nested_dict(pnu_res.json(), "familyNumber")
                                            except: pass 
                        if not park_count:
                            try: 
                                park_count = find_key_in_nested_dict(info_json, "totalParkingCount") 
                            except: pass 
                        if not detail_addr:
                            try: 
                                dong_eup_myeon_code = find_key_in_nested_dict(info_json, "legalDivisionNumber")
                                jibun = find_key_in_nested_dict(info_json, "jibun")
                                dong_eup_myeon = find_keys_with_value(rls, dong_eup_myeon_code)
                                detail_addr = f'{dong_eup_myeon if dong_eup_myeon else ""} {jibun if jibun else ""}'.strip()
                            except: pass 
                    except: pass 
                except:
                    pass 

                agents_url = f"https://new.land.naver.com/api/articles?representativeArticleNo={new_c_no}"

                try:
                    agents_res = sess.get(agents_url)
                    if agents_res.status_code != 200:
                        raise Exception 
                    print(agents_res)
                    agent_num = len(agents_res.json()) 
                except: pass 

                article_realtor = c_info.get("articleRealtor", "")
                agent_name = article_realtor.get("realtorName", "") if article_realtor else None 
                agent_man_name = article_realtor.get("representativeName", "") if article_realtor else None 
                agent_addr = article_realtor.get("address", "") if article_realtor else None 
                agent_no = article_realtor.get("establishRegistrationNo", "") if article_realtor else None 
                agent_tel = article_realtor.get("representativeTelNo", "") if article_realtor else None # 중개사 전화 
                agent_phone = article_realtor.get("cellPhoneNo", "") if article_realtor else None # 중개사 휴대폰

                if not biz_step or not construction_company_name:
                    biz_url = f"https://fin.land.naver.com/front-api/v1/complex/reconstruction?complexNumber={c_no}"
                    try:
                        biz_res = sess.get(biz_url)
                        if biz_res.status_code != 200: raise Exception
                        print(biz_res)
                        if not construction_company_name:
                            try:
                                construction_company_name = biz_res.json().get("result").get('constructionCompany')
                            except: pass 
                        if not biz_step:
                            try: 
                                biz_step_code = biz_res.json().get("result").get("currentBusinessStep").get("stepType")
                                if biz_step_code:
                                    biz_step = biz_step_types[biz_step_code]
                            except: pass 
                    except: pass 

                if all_warrant_price != None and all_warrant_price != "":
                    all_warrant_price = all_warrant_price if int(all_warrant_price.replace(",","") if isinstance(all_warrant_price, str) else all_warrant_price) != 0 else None 
                if all_rent_price != None and all_rent_price != "":
                    all_rent_price = all_rent_price if int(all_rent_price.replace(",","") if isinstance(all_rent_price, str) else all_rent_price) != 0 else None 
                if dong_num != None and dong_num != "":
                    dong_num = None if int(dong_num) == 0 else dong_num 
                if park_count != None and dong_num != "":
                    park_count = None if int(park_count) == 0 else park_count
                if yj_rate:
                    if yj_rate == "-":
                        yj_rate = None
                    else: 
                        yj_rate = int(float(yj_rate))
                if gp_rate:
                    if gp_rate == "-":
                        gp_rate = None 
                    else:
                        gp_rate = int(float(gp_rate))
                if management_cost == 0:
                    management_cost = None 

                temp_data = [
                    addr_si,
                    addr_gu,
                    addr_dong,
                    f"https://new.land.naver.com/{url_realestate_type_dict[realestate_type_code]}?articleNo={new_c_no}",
                    expose_start_ymd,
                    verification_type_name,
                    realestate_type,
                    trade_type,
                    name,
                    dong,
                    area1,
                    area2,
                    arch_area,
                    exclusive_rate,
                    yj_rate,
                    gp_rate,
                    floor,
                    total_floor,
                    direction,
                    deal_price,
                    rent_price,
                    price_by_space,
                    gongsi_std_ymd,
                    gongsi_min_price,
                    gongsi_max_price,
                    right_price,
                    finance_price,
                    all_warrant_price,
                    all_rent_price,
                    premium_price,
                    biz_step,
                    usage_district,
                    management_cost,
                    room_count,
                    bathroom_count,
                    nanbang,
                    current_usage,
                    recommend_usage,
                    building_usage,
                    jisang_jiha_floor,
                    movein_possible_ymd,
                    simple_description, 
                    detail_description,
                    sojaeji,
                    addr,
                    detail_addr,
                    lat_long,
                    construction_company_name,
                    apt_use_approve_ymd,
                    saede_num,
                    dong_num,
                    park_count, 
                    agent_num, 
                    agent_name,
                    agent_man_name,
                    agent_addr,
                    agent_no,
                    agent_tel,
                    agent_phone,
                ]

                data.append(temp_data)
                
            except Exception as e: 
                print(e)

    else:
        data.append(list(c["in_data"].values()))

    return data 


def load_rls_file():

    import sys, os 

    # if hasattr(sys, "_MEIPASS"):
    #     base_path = sys._MEIPASS
    # else:
    #     base_path = os.path.dirname(__file__)

    # file_path = os.path.join(base_path, "naver_rls.json")

    file_path = "naver_rls.json"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as e:
        print("naver_rls.json 파일이 발견되지 않았습니다", e)
        assert False 
    
rls = load_rls_file()
########################################################################################################################
import tkinter as tk
from tkinter import ttk, messagebox

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        
        canvas = tk.Canvas(self, bg="#f0f0f0")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas) 

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.scrollable_frame.bind("<Enter>", lambda e: self._bind_to_mousewheel(canvas))
        self.scrollable_frame.bind("<Leave>", lambda e: self._unbind_from_mousewheel(canvas))
    
    def _bind_to_mousewheel(self, canvas):
        if canvas.tk.call('tk', 'windowingsystem') == 'aqua':
            canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta)), "units"))
        else:
            canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta/120)), "units"))
            canvas.bind_all("<Button-4>", lambda event: canvas.yview_scroll(-1, "units")) 
            canvas.bind_all("<Button-5>", lambda event: canvas.yview_scroll(1, "units"))  
    
    def _unbind_from_mousewheel(self, canvas):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

root = tk.Tk()
root.title("네이버부동산 크롤러")
root.geometry(f"500x800") 
root.configure(bg="#f0f0f0")

style = ttk.Style(root)
style.theme_use('default')
style.configure("TButton", font=("Arial", 12))
style.configure("TLabel", font=("Arial", 12))
style.configure("Header.TLabel", font=("Arial", 14, "bold"))
style.configure("TCheckbutton", font=("Arial", 10))

main_frame = ttk.Frame(root, padding=10)
main_frame.pack(fill="both", expand=True)

scrollable_main = ScrollableFrame(main_frame)
scrollable_main.pack(fill="both", expand=True)

region_frame = ttk.LabelFrame(scrollable_main.scrollable_frame, text="지역 선택", padding=10)
region_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")

selected_si = tk.StringVar(value="시 선택")
selected_gu = tk.StringVar(value="구 선택")
selected_dong = tk.StringVar(value="동 선택")

def update_gu(*args):
    sido = selected_si.get()
    if sido not in rls:
        selected_gu.set("구 선택")
        selected_dong.set("동 선택")  # 구를 선택하지 않으면 동도 초기화
        dong_menu['menu'].delete(0, 'end')
        dong_menu['menu'].add_command(label="동 선택", command=lambda: selected_dong.set("동 선택"))
        return

    gu_options = list(rls[sido].keys())
    selected_gu.set("구 선택")  # 구를 선택할 때마다 기본값으로 "구 선택"으로 설정

    gu_menu['menu'].delete(0, 'end')
    for gu in gu_options:
        gu_menu['menu'].add_command(label=gu, command=lambda value=gu: selected_gu.set(value))

    update_dong()  # 구가 변경되면 동도 초기화

def update_dong(*args):
    si = selected_si.get()
    gu = selected_gu.get()

    if si not in rls or gu not in rls[si]:
        selected_dong.set("동 선택")
        dong_menu['menu'].delete(0, 'end')
        dong_menu['menu'].add_command(label="동 선택", command=lambda: selected_dong.set("동 선택"))
        return

    dong_options = list(rls[si][gu].keys())
    selected_dong.set("동 선택")  # 동을 선택할 때마다 기본값으로 "동 선택"으로 설정

    dong_menu['menu'].delete(0, 'end')
    for dong in dong_options:
        dong_menu['menu'].add_command(label=dong, command=lambda value=dong: selected_dong.set(value))


si_menu = ttk.OptionMenu(region_frame, selected_si, "시 선택", *rls.keys())
si_menu.grid(row=0, column=0, padx=5, pady=5, sticky="w")

gu_menu = ttk.OptionMenu(region_frame, selected_gu, "구 선택")
gu_menu.grid(row=0, column=1, padx=5, pady=5, sticky="w")

dong_menu = ttk.OptionMenu(region_frame, selected_dong, "동 선택")
dong_menu.grid(row=0, column=2, padx=5, pady=5, sticky="w")

selected_si.trace_add('write', update_gu)
selected_gu.trace_add('write', update_dong)

filter_frame = ttk.LabelFrame(scrollable_main.scrollable_frame, text="필터 선택", padding=10)
filter_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")

def create_checkboxes(parent, options, selected_vars, title, max_per_row=4):
    frame = ttk.LabelFrame(parent, text=title, padding=10)
    frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")

    for idx, option in enumerate(options):
        var = tk.BooleanVar()
        selected_vars[option] = var
        cb = ttk.Checkbutton(frame, text=option, variable=var)
        
        # Grid layout으로 줄바꿈 처리
        row = idx // max_per_row
        col = idx % max_per_row
        cb.grid(row=row, column=col, sticky="w", padx=5, pady=5)

# 아파트 구분 체크박스
apartment_options = [
    "아파트",
    "아파트분양권",
    "재건축",
    "오피스텔",
    "오피스텔분양권",
    "재개발",
    "분양중/예정",
    "빌라/연립",
    "단독/다가구",
    "전원주택",
    "상가주택",
    "한옥주택",
    "원룸",
    "투룸",
    "상가",
    "사무실",
    "공장/창고",
    "지식산업센터",
    "건물",
    "토지"
]
selected_apartment_options = {}
create_checkboxes(filter_frame, apartment_options, selected_apartment_options, "아파트 구분")

# 거래유형 체크박스
transaction_options = [
    "매매",
    "전세",
    "월세",
    "단기임대",
]
selected_transaction_options = {}
create_checkboxes(filter_frame, transaction_options, selected_transaction_options, "거래유형")

def create_range_options(parent, label_text, options_dict, var_left, var_right):
    frame = ttk.LabelFrame(parent, text=label_text, padding=10)
    frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")

    left_menu = ttk.OptionMenu(frame, var_left, "무관", *options_dict.keys())
    left_menu.pack(side="left", padx=5, pady=5)

    tilde = ttk.Label(frame, text="~")
    tilde.pack(side="left")

    right_menu = ttk.OptionMenu(frame, var_right, "무관", *options_dict.keys())
    right_menu.pack(side="left", padx=5, pady=5)

# 매매가 옵션
deal_price_dict = {
    "무관": None,
    "5천": 5000,
    "6천" : 6000,
    "7천" : 7000,
    "8천" : 8000,
    "9천" : 9000,
    "1억": 10000,
    "2억": 20000,
    "3억": 30000,
    "4억": 40000,
    "5억": 50000,
    "6억": 60000,
    "7억": 70000,
    "8억": 80000,
    "9억": 90000,
    "10억": 100000,
    "11억": 110000,
    "12억": 120000,
    "13억": 130000,
    "14억": 140000,
    "15억": 150000,
    "16억": 160000,
    "17억": 170000,
    "18억": 180000,
}
deal_price_option_L = tk.StringVar(value="무관")
deal_price_option_R = tk.StringVar(value="무관")
create_range_options(filter_frame, "매매가", deal_price_dict, deal_price_option_L, deal_price_option_R)

# 보증금 옵션
warranty_price_dict = {
    "무관": None,
    "1천": 1000,
    "2천": 2000,
    "3천": 3000,
    "4천": 4000,
    "5천": 5000,
    "6천": 6000,
    "7천": 7000,
    "8천": 8000,
    "9천": 9000,
    "1억": 10000,
    "2억": 20000,
    "3억": 30000,
    "4억": 40000,
    "5억": 50000
}
warranty_price_option_L = tk.StringVar(value="무관")
warranty_price_option_R = tk.StringVar(value="무관")
create_range_options(filter_frame, "보증금", warranty_price_dict, warranty_price_option_L, warranty_price_option_R)

# 월세 옵션
rent_price_dict = {
    "무관": None,
    "10" : 10,
    "20": 20,
    "30": 30,
    "40": 40,
    "50": 50,
    "60": 60,
    "70": 70,
    "80": 80,
    "90": 90,
    "1백": 100,
    "2백": 200,
}
rent_price_option_L = tk.StringVar(value="무관")
rent_price_option_R = tk.StringVar(value="무관")
create_range_options(filter_frame, "월세", rent_price_dict, rent_price_option_L, rent_price_option_R)

# 면적 옵션
area_dict = {
    "무관": None,
    "10평": 33,
    "20평": 66,
    "30평": 99,
    "40평": 132,
    "50평": 165,
    "60평": 198,
    "70평": 231
}
area_option_L = tk.StringVar(value="무관")
area_option_R = tk.StringVar(value="무관")
create_range_options(filter_frame, "면적", area_dict, area_option_L, area_option_R)

from functools import partial

def create_exclusive_checkboxes(parent, options, selected_vars, title):
    frame = ttk.LabelFrame(parent, text=title, padding=10)
    frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")
    
    def on_check(var, option, *args):
        if var.get():  
            for key in selected_vars:
                if key != option:
                    selected_vars[key].set(False)
    
    for option in options:
        var = tk.BooleanVar()
        selected_vars[option] = var
        
        if option == "전체":
            var.set(True)
        
        var.trace_add("write", partial(on_check, var, option))
        
        cb = ttk.Checkbutton(frame, text=option, variable=var)
        cb.pack(side="left", padx=5, pady=5)

date_dict = {
    "전체" : None,
    "오늘" : 1,
    "어제/오늘" : 2,
    "일주일" : 7,
    "한달" : 30
}
date_options = list(date_dict.keys())
selected_date_options = {} 
create_exclusive_checkboxes(filter_frame, date_options, selected_date_options, "등록일")

button_frame = ttk.Frame(scrollable_main.scrollable_frame, padding=10)
button_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="w")

def search():

    selected_items.clear()

    global cls 
    # JGC:PRE:OBYG:APT:ABYG:JGB:OPST # SG:SMS:GJCG:APTHGJ:GM:TJ
    JGC = ("JGC" if selected_apartment_options["재건축"].get() else "")
    PRE = ("IA01:IA02:IC01:IC02:IA04:IC03" if selected_apartment_options["분양중/예정"].get() else "")
    OBYG = ("OBYG" if selected_apartment_options["오피스텔분양권"].get() else "")
    APT = ("APT" if selected_apartment_options["아파트"].get() else "")
    ABYG = ("ABYG" if selected_apartment_options["아파트분양권"].get() else "")
    JGB = ("JGB" if selected_apartment_options["재개발"].get() else "")
    OPST = ("OPST" if selected_apartment_options["오피스텔"].get() else "")
    VL = ("VL" if selected_apartment_options["빌라/연립"].get() else "")
    DDDGG = ("DDDGG" if selected_apartment_options["단독/다가구"].get() else "")
    JWJT = ("JWJT" if selected_apartment_options["전원주택"].get() else "")
    SGJT = ("SGJT" if selected_apartment_options["상가주택"].get() else "")
    HOJT = ("HOJT" if selected_apartment_options["한옥주택"].get() else "")
    OR = ("OR" if selected_apartment_options["원룸"].get() or selected_apartment_options["투룸"].get() else "")
    SG = ("SG" if selected_apartment_options["상가"].get() else "")
    SMS = ("SMS" if selected_apartment_options["사무실"].get() else "")
    GJCG = ("GJCG" if selected_apartment_options["공장/창고"].get() else "")
    APTHGJ = ("APTHGJ" if selected_apartment_options["지식산업센터"].get() else "")
    GM = ("GM" if selected_apartment_options["건물"].get() else "")
    TJ = ("TJ" if selected_apartment_options["토지"].get() else "")

    realestate_type = ":".join([t for t in [JGC, PRE, OBYG, APT, ABYG, JGB, OPST, VL, DDDGG, JWJT, SGJT, HOJT, OR, SG, SMS, GJCG, APTHGJ, GM, TJ] if t])

    # if OR:
    #     if selected_apartment_options["원룸"].get() and not selected_apartment_options["투룸"].get():
    #         tag = ":::::::ONEROOM:"
    #     elif not selected_apartment_options["원룸"].get() and selected_apartment_options["투룸"].get():
    #         tag = ":::::::TWOROOM:"
    #     else:
    #         tag = ":::::::SMALLSPCRENT:"
    # else: tag = "::::::::"
    tag = "::::::::"

    A1 = ("A1" if selected_transaction_options["매매"].get() else "")
    B1 = ("B1" if selected_transaction_options["전세"].get() else "")
    B2 = ("B2" if selected_transaction_options["월세"].get() else "")
    B3 = ("B3" if selected_transaction_options["단기임대"].get() else "")
    trade_type = ":".join(t for t in [A1, B1, B2, B3] if t) 
    
    min_deal_price = deal_price_dict[deal_price_option_L.get()]
    max_deal_price = deal_price_dict[deal_price_option_R.get()]

    min_warranty_price = warranty_price_dict[warranty_price_option_L.get()]
    max_warranty_price = warranty_price_dict[warranty_price_option_R.get()]

    min_rent_price = rent_price_dict[rent_price_option_L.get()]
    max_rent_price = rent_price_dict[rent_price_option_R.get()]

    min_area = area_dict[area_option_L.get()]
    max_area = area_dict[area_option_R.get()]

    date_key = [key for key, value in selected_date_options.items() if value.get()]
    max_days_from_now = date_dict[date_key[0]]

    r = get_r(selected_si.get(), selected_gu.get(), selected_dong.get())

    cls = get_cls(*r, realestate_type=realestate_type, tag=tag,
                  trade_type=trade_type, min_deal_price=min_deal_price, max_deal_price=max_deal_price, 
                  min_warranty_price=min_warranty_price, max_warranty_price=max_warranty_price, 
                  min_rent_price=min_rent_price, max_rent_price=max_rent_price, 
                  min_area=min_area, max_area=max_area, max_days_from_now=max_days_from_now)
    
    print(f"{len(cls)}개 조회됨")

    create_cls_checkboxes(checkbox_frame, cls)

search_button = ttk.Button(button_frame, text="검색", command=search)
search_button.pack(side="left", padx=10, pady=10)

def exec():
    global cls 
    # print(selected_items)
    selected_cls_idx_list = [i for i, (key, value) in enumerate(selected_items.items()) if value.get()]
    # print(selected_cls_idx_list)
    filtered_cls = [cls[i] for i in selected_cls_idx_list]

    JGC = ("JGC" if selected_apartment_options["재건축"].get() else "")
    PRE = ("IA01:IA02:IC01:IC02:IA04:IC03" if selected_apartment_options["분양중/예정"].get() else "")
    OBYG = ("OBYG" if selected_apartment_options["오피스텔분양권"].get() else "")
    APT = ("APT" if selected_apartment_options["아파트"].get() else "")
    ABYG = ("ABYG" if selected_apartment_options["아파트분양권"].get() else "")
    JGB = ("JGB" if selected_apartment_options["재개발"].get() else "")
    OPST = ("OPST" if selected_apartment_options["오피스텔"].get() else "")
    VL = ("VL" if selected_apartment_options["빌라/연립"].get() else "")
    DDDGG = ("DDDGG" if selected_apartment_options["단독/다가구"].get() else "")
    JWJT = ("JWJT" if selected_apartment_options["전원주택"].get() else "")
    SGJT = ("SGJT" if selected_apartment_options["상가주택"].get() else "")
    HOJT = ("HOJT" if selected_apartment_options["한옥주택"].get() else "")
    OR = ("OR" if selected_apartment_options["원룸"].get() or selected_apartment_options["투룸"].get() else "")
    SG = ("SG" if selected_apartment_options["상가"].get() else "")
    SMS = ("SMS" if selected_apartment_options["사무실"].get() else "")
    GJCG = ("GJCG" if selected_apartment_options["공장/창고"].get() else "")
    APTHGJ = ("APTHGJ" if selected_apartment_options["지식산업센터"].get() else "")
    GM = ("GM" if selected_apartment_options["건물"].get() else "")
    TJ = ("TJ" if selected_apartment_options["토지"].get() else "")

    realestate_type = ":".join([t for t in [JGC, PRE, OBYG, APT, ABYG, JGB, OPST, VL, DDDGG, JWJT, SGJT, HOJT, OR, SG, SMS, GJCG, APTHGJ, GM, TJ] if t])

    # if OR:
    #     if selected_apartment_options["원룸"].get() and not selected_apartment_options["투룸"].get():
    #         tag = ":::::::ONEROOM:"
    #     elif not selected_apartment_options["원룸"].get() and selected_apartment_options["투룸"].get():
    #         tag = ":::::::TWOROOM:"
    #     else:
    #         tag = ":::::::SMALLSPCRENT:"
    # else: tag = "::::::::"
    tag = "::::::::"

    A1 = ("A1" if selected_transaction_options["매매"].get() else "")
    B1 = ("B1" if selected_transaction_options["전세"].get() else "")
    B2 = ("B2" if selected_transaction_options["월세"].get() else "")
    B3 = ("B3" if selected_transaction_options["단기임대"].get() else "")
    trade_type = ":".join(t for t in [A1, B1, B2, B3] if t) 
    
    min_deal_price = deal_price_dict[deal_price_option_L.get()]
    max_deal_price = deal_price_dict[deal_price_option_R.get()]

    min_warranty_price = warranty_price_dict[warranty_price_option_L.get()]
    max_warranty_price = warranty_price_dict[warranty_price_option_R.get()]

    min_rent_price = rent_price_dict[rent_price_option_L.get()]
    max_rent_price = rent_price_dict[rent_price_option_R.get()]

    min_area = area_dict[area_option_L.get()]
    max_area = area_dict[area_option_R.get()]

    messagebox.showinfo("알림", "작업을 시작합니다.")
    
    data = []
    for i, c in enumerate(filtered_cls):
        print(f"\n{i + 1}/{len(filtered_cls)} {c} 진행중...")
        data.extend(get_complex_info(c, realestate_type=realestate_type, tag=tag,
                  trade_type=trade_type, min_deal_price=min_deal_price, max_deal_price=max_deal_price, 
                  min_warranty_price=min_warranty_price, max_warranty_price=max_warranty_price, 
                  min_rent_price=min_rent_price, max_rent_price=max_rent_price, 
                  min_area=min_area, max_area=max_area))

    if len(data) == 0:
        messagebox.showerror("알림", "저장된 데이터가 없습니다.")
        return 
    
    import pandas as pd 
    
    df = pd.DataFrame(data)
    df.columns = [
        "시",
        "구",
        "동",
        '매물번호',
        '등록/확인일',
        '집주인/확인',
        '종류',
        '거래방식',
        '매물명',
        '아파트동',
        '공급/계약/대지',
        '전용/연',
        '건면적',
        '전용률',
        '용적률',
        '건폐율',
        '해당층',
        '전체층',
        '방향',
        '매매/전세금',
        '월세',
        '평단가',
        '공시기준일',
        '공시가(최저)',
        '공시가(최고)',
        '권리금',
        '융자금',
        '기보증금',
        '기월세',
        '프리미엄',
        '사업시행단계',
        '용도지역',
        '관리비',
        '방수',
        '화장실수',
        '난방',
        '현재업종',
        '추천업종',
        '건축물용도',
        '지상층/지하층',
        '입주가능일',
        '간략설명',
        '설명',
        '소재지',
        '주소',
        '세부주소',
        '위도/경도',
        '건설사',
        '사용승인일',
        '세대수',
        '동수',
        '주차가능수',
        '중개사수',
        '중개사무소명',
        '중개사명',
        '중개사주소',
        '중개사등록번호',
        '중개사전화',
        '중개사휴대폰'
    ]
    
    import time, re 

    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    df = df.map(lambda x: ILLEGAL_CHARACTERS_RE.sub(r'', x) if isinstance(x, str) else x)
    # df.fillna('', inplace=True)
    df.to_excel(f"data_{int(time.time())}.xlsx", index=False)
    
    messagebox.showinfo("알림", "작업을 완료했습니다.")

exec_button = ttk.Button(button_frame, text="실행", command=exec)
exec_button.pack(side="left", padx=10, pady=10)

result_frame = ttk.LabelFrame(scrollable_main.scrollable_frame, text="검색결과", padding=10)
result_frame.pack(fill="both", expand=True, padx=5, pady=5, anchor="w")

result_scrollable = ScrollableFrame(result_frame)
result_scrollable.pack(fill="both", expand=True)

checkbox_frame = tk.Frame(result_scrollable.scrollable_frame, bg="white")
checkbox_frame.pack(fill="both", expand=True, anchor="w")

selected_items = {}

def create_cls_checkboxes(parent, data):
    for widget in parent.winfo_children():
        widget.destroy()

    select_all_var = tk.BooleanVar(value=False)

    def toggle_all():
        for var in selected_items.values():
            var.set(select_all_var.get())

    select_all_checkbox = ttk.Checkbutton(
        parent,
        text="전체선택",
        variable=select_all_var,
        command=toggle_all
    )
    select_all_checkbox.pack(anchor="w", pady=5)

    for item in data:
        label = f'{item["complex_name"]} ({item["realestate_type_name"]}) [{item["complex_no"]}]'
        selected_items[label] = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(parent, text=label, variable=selected_items[label])
        cb.pack(anchor="w", pady=2)

    parent.update_idletasks()
    parent.master.update_idletasks()

main_frame.rowconfigure(0, weight=1)
main_frame.columnconfigure(0, weight=1)

if __name__ == "__main__":
    
    # from codecoon_server_manager.auth import check_auth
    # check_auth('SBC_네이버부동산', 'CodeCoon', 365)
    
    root.mainloop()
# PyInstaller 전용: app_v1_free_trial 등은 .pyd라 정적 분석이 안 되므로,
# 여기서 한 번 import 해 두면 분석 그래프에 의존성이 잡힘 (spec에 패키지 나열 불필요).
# requirements.txt와 맞춰 두고, 라이브러리 추가 시 여기만 수정하면 됨.

# Cython으로 같이 빌드되는 동일 프로젝트 모듈(.pyd)
import app_main_common  # noqa: F401
import schedule_manager  # noqa: F401
import schedule_dialog  # noqa: F401
import schedule_mixin  # noqa: F401
import app_v1_main  # noqa: F401
import app_v1_site_main  # noqa: F401
import app_v2_main  # noqa: F401
import free_trial_app_shared  # noqa: F401
import daangn_realty_crawler  # noqa: F401
import peterpan_crawler  # noqa: F401
import onhouse_crawler  # noqa: F401
import naver_crawler  # noqa: F401

import PySide6.QtCore  # noqa: F401
import PySide6.QtGui  # noqa: F401
import PySide6.QtWidgets  # noqa: F401

import numpy  # noqa: F401
import pandas  # noqa: F401

import curl_cffi  # noqa: F401
import tls_client  # noqa: F401
import bs4  # noqa: F401
import lxml  # noqa: F401
import lxml.etree  # noqa: F401
import openpyxl  # noqa: F401
import requests  # noqa: F401

import codecoon_server_manager.auth  # noqa: F401

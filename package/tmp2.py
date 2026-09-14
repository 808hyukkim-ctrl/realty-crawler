import pandas as pd 
from app_v2 import NaverWorker



path = 'data\네이버_서울특별시_강남구_개포동_207건_260402_120623.xlsx'
n = NaverWorker({})
n._apply_excel_hyperlinks(path)
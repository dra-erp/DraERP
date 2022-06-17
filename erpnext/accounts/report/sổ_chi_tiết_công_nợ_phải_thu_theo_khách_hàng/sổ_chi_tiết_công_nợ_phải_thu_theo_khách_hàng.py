# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
from dataclasses import asdict
import frappe



def execute(filters=None):
    columns, data = [], []
    columns = [		"soHieu"
					,"ngayThang"
					,"kyHieu"
					,"soHoaDon"
					,"dienGiai"
					,"taiKhoanDoiUng"
					,"phatSinhNo"
					,"phatSinhCo"
					,"soDuNo"
					,"soDuCo"
					,"taiKhoanNo"
					,"taiKhoanCo"

        ]
    data = frappe.db.sql(""" 

			SELECT 
				voucher_no AS soHieu										
				, date( creation)AS ngayThang
				, '' AS kyHieu
				, voucher_no AS soHoaDon
				, voucher_type AS dienGiai
				, '' taiKhoanDoiUng
				, debit AS phatSinhNo
				, credit AS phatSinhCo
				, 0 soDuNo
				, 0 soDuCo
				, TRIM(SUBSTRING_INDEX(ACCOUNT, '-', 1)) AS taiKhoanNo
				, TRIM(SUBSTRING_INDEX(AGAINST, '-', 1)) AS taiKhoanCo


			FROM `tabGL Entry`
			



			WHERE  		ACCOUNT LIKE '1311%'
						OR  ACCOUNT LIKE '13621%'
						OR  ACCOUNT LIKE '13631%' 
						OR  ACCOUNT LIKE '13681%'
						OR  ACCOUNT LIKE '337%' 
						OR  ACCOUNT LIKE '12831%' 
						OR  ACCOUNT LIKE '1411%'
						OR  ACCOUNT LIKE '2441%'
						OR  ACCOUNT LIKE '13851%'
						OR  ACCOUNT LIKE '13881%'
						OR  ACCOUNT LIKE '3381%'
						OR  ACCOUNT LIKE '3382%'
						OR  ACCOUNT LIKE '3383%'
						OR  ACCOUNT LIKE '3384%'
						OR  ACCOUNT LIKE '33851%'
						OR  ACCOUNT LIKE '3386%'
						OR  ACCOUNT LIKE '33871%'
						OR  ACCOUNT LIKE '33881%'
						OR  ACCOUNT LIKE '22931%'
						OR  ACCOUNT LIKE '1312%'
						OR  ACCOUNT LIKE '13622%'
						OR  ACCOUNT LIKE '13632%'
						OR  ACCOUNT LIKE '13682%'
						OR  ACCOUNT LIKE '12832%'
						OR  ACCOUNT LIKE '1412%'
						OR  ACCOUNT LIKE '2442%'
						OR  ACCOUNT LIKE '13852%'
						OR  ACCOUNT LIKE '13882%'
						OR  ACCOUNT LIKE '33852%'
						OR  ACCOUNT LIKE '33872%'
						OR  ACCOUNT LIKE '33882%'
						OR  ACCOUNT LIKE '22932%'
						
						AND fiscal_year=2022
						AND (company = 'Fintech DRACO'  OR company is null  or company = '')
						AND is_cancelled=0
			limit 100				
			""")


    return columns, data








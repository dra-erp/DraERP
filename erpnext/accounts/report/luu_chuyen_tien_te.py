# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import functools
import math
from pydoc import tempfilepager
import re
import tempfile

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, flt, formatdate, get_first_day, getdate, log

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency
from erpnext.accounts.utils import get_fiscal_year
from pymysql import NULL

class TaiKhoan:
	tenTaiKhoanCo=''
	tenTaiKhoanNo=''
	tienCo=0
	tienNo=0
	def __init__(self):
		pass
	def KhoiTao(self, tenTaiKhoanCo,tenTaiKhoanNo, tienCo,tienNo):
		self.tenTaiKhoanCo = tenTaiKhoanCo
		self.tienCo = tienCo
		self.tenTaiKhoanNo = tenTaiKhoanNo
		self.tienNo = tienNo


def layDanhSachTuGLEntryTestTheoMaSoYearly(account,against,nam,company):
	input={
		"account":account,
		"against":against,
		"nam":nam,
		"company":company
	}
	return frappe.db.sql("""
		select posting_date,voucher_no,TRIM(SUBSTRING_INDEX(ACCOUNT, '-', 1)) AS account,debit,credit,debit_in_account_currency,credit_in_account_currency,company,fiscal_year
		from `tabGL Entry`
		WHERE ((ACCOUNT LIKE %(account)s AND AGAINST LIKE %(against)s)
			OR	(ACCOUNT LIKE %(account)s AND AGAINST IN (
				SELECT party FROM `tabGL Entry` WHERE ACCOUNT LIKE %(against)s AND AGAINST LIKE %(account)s
				))	
			OR ACCOUNT LIKE %(account)s
			)
			AND is_cancelled=0
			and fiscal_year=%(nam)s
			and company=%(company)s
			ORDER BY voucher_no
		""",input,as_dict=True)

def layDanhSachTuGLEntryTestTheoMaSoKhacYearly(account,against,nam,company):
	input={
		"account":account,
		"against":against,
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"company":company
	}
	return frappe.db.sql("""
		select posting_date,voucher_no,TRIM(SUBSTRING_INDEX(ACCOUNT, '-', 1)) AS account,debit,credit,debit_in_account_currency,credit_in_account_currency,company,fiscal_year
		from `tabGL Entry`
		WHERE ((ACCOUNT LIKE %(account)s AND AGAINST LIKE %(against)s)
			OR	(ACCOUNT LIKE %(account)s AND AGAINST IN (
				SELECT party FROM `tabGL Entry` WHERE ACCOUNT LIKE %(against)s AND AGAINST LIKE %(account)s
				))	
			OR ACCOUNT LIKE %(account)s
			)
			AND is_cancelled=0
			and (
				posting_date >= %(from_date)s
				and posting_date < %(to_date)s
			)
			and company=%(company)s
			ORDER BY voucher_no
		""",input,as_dict=True)

def viTriTienLonNhat(list):
	tk=list[0]
	vt=0
	for i in range(len(list)):
		if list[i].debit>tk.debit and list[i].debit > tk.credit:
			tk=list[i]
			vt=i
		if list[i].credit>tk.credit and list[i].credit>tk.debit:
			tk=list[i]
			vt=i
	return vt

def layDSTheoVoucherNo(voucher_no):
	test={
		"voucher_no":voucher_no
	}
	list=frappe.db.sql("""
		select posting_date,voucher_no,debit,credit,debit_in_account_currency,credit_in_account_currency,company,fiscal_year,TRIM(SUBSTRING_INDEX(ACCOUNT, '-', 1)) AS account
		from `tabGL Entry` where voucher_no=%(voucher_no)s
		and is_cancelled='0'
		""",test,as_dict=True)
	for j in list:
		a=j.debit-j.credit
		if a<0:
			j.debit=0
			j.credit=-a
		if a==0:
			j.debit=0
			j.credit=0
		if a>0:
			j.debit=a
			j.credit=0
	return list

def phanTichDuLieu(list):
	lr=[]
	vt=viTriTienLonNhat(list)
	for  i in range(len(list)):
		if i==vt:
			pass
		else:
			tmp=TaiKhoan()
			if list[i].debit==0 and list[i].credit==0:
				pass

			else:
				if list[i].debit>0:
					tmp.tenTaiKhoanNo=list[i].account
					tmp.tienNo=list[i].debit
					tmp.tenTaiKhoanCo=list[vt].account
					tmp.tienCo=0
				if list[i].credit>0:
					tmp.tenTaiKhoanNo=list[vt].account
					tmp.tienNo=0
					tmp.tenTaiKhoanCo=list[i].account
					tmp.tienCo=list[i].credit
				if tmp.tenTaiKhoanCo!=tmp.tenTaiKhoanNo:
					lr.append(tmp)
	return lr

def get_period_list(from_fiscal_year, to_fiscal_year, period_start_date, period_end_date, filter_based_on, periodicity, accumulated_values=False,
	company=None, reset_period_on_fy_change=True, ignore_fiscal_year=False):
	"""Get a list of dict {"from_date": from_date, "to_date": to_date, "key": key, "label": label}
		Periodicity can be (Yearly, Quarterly, Monthly)"""

	if filter_based_on == 'Fiscal Year':
		fiscal_year = get_fiscal_year_data(from_fiscal_year, to_fiscal_year)
		validate_fiscal_year(fiscal_year, from_fiscal_year, to_fiscal_year)
		year_start_date = getdate(fiscal_year.year_start_date)
		year_end_date = getdate(fiscal_year.year_end_date)
	else:
		validate_dates(period_start_date, period_end_date)
		year_start_date = getdate(period_start_date)
		year_end_date = getdate(period_end_date)

	months_to_add = {
		"Yearly": 12,
		"Half-Yearly": 6,
		"Quarterly": 3,
		"Monthly": 1
	}[periodicity]

	period_list = []

	start_date = year_start_date
	months = get_months(year_start_date, year_end_date)

	for i in range(cint(math.ceil(months / months_to_add))):
		period = frappe._dict({
			"from_date": start_date
		})

		if i==0 and filter_based_on == 'Date Range':
			to_date = add_months(get_first_day(start_date), months_to_add)
		else:
			to_date = add_months(start_date, months_to_add)

		start_date = to_date

		# Subtract one day from to_date, as it may be first day in next fiscal year or month
		to_date = add_days(to_date, -1)

		if to_date <= year_end_date:
			# the normal case
			period.to_date = to_date
		else:
			# if a fiscal year ends before a 12 month period
			period.to_date = year_end_date

		# if not ignore_fiscal_year:
		# 	period.to_date_fiscal_year = get_fiscal_year(period.to_date, company=company)[0]
		# 	period.from_date_fiscal_year_start_date = get_fiscal_year(period.from_date, company=company)[1]

		period_list.append(period)

		if period.to_date == year_end_date:
			break

	# common processing
	for opts in period_list:
		key = opts["to_date"].strftime("%b_%Y").lower()
		if periodicity == "Monthly" and not accumulated_values:
			label = formatdate(opts["to_date"], "MMM YYYY")
		else:
			if not accumulated_values:
				label = get_label(periodicity, opts["from_date"], opts["to_date"])
			else:
				if reset_period_on_fy_change:
					label = get_label(periodicity, opts.from_date_fiscal_year_start_date, opts["to_date"])
				else:
					label = get_label(periodicity, period_list[0].from_date, opts["to_date"])

		opts.update({
			"key": key.replace(" ", "_").replace("-", "_"),
			"label": label,
			"year_start_date": year_start_date,
			"year_end_date": year_end_date,
			"periodicity": periodicity
		})

	return period_list


def get_fiscal_year_data(from_fiscal_year, to_fiscal_year):
	fiscal_year = frappe.db.sql("""select min(year_start_date) as year_start_date,
		max(year_end_date) as year_end_date from `tabFiscal Year` where
		name between %(from_fiscal_year)s and %(to_fiscal_year)s""",
		{'from_fiscal_year': from_fiscal_year, 'to_fiscal_year': to_fiscal_year}, as_dict=1)

	return fiscal_year[0] if fiscal_year else {}


def validate_fiscal_year(fiscal_year, from_fiscal_year, to_fiscal_year):
	if not fiscal_year.get('year_start_date') or not fiscal_year.get('year_end_date'):
		frappe.throw(_("Start Year and End Year are mandatory"))

	if getdate(fiscal_year.get('year_end_date')) < getdate(fiscal_year.get('year_start_date')):
		frappe.throw(_("End Year cannot be before Start Year"))

def validate_dates(from_date, to_date):
	if not from_date or not to_date:
		frappe.throw(_("From Date and To Date are mandatory"))

	if to_date < from_date:
		frappe.throw(_("To Date cannot be less than From Date"))

def get_months(start_date, end_date):
	diff = (12 * end_date.year + end_date.month) - (12 * start_date.year + start_date.month)
	return diff + 1


def get_label(periodicity, from_date, to_date):
	if periodicity == "Yearly":
		if formatdate(from_date, "YYYY") == formatdate(to_date, "YYYY"):
			label = formatdate(from_date, "YYYY")
		else:
			label = formatdate(from_date, "YYYY") + "-" + formatdate(to_date, "YYYY")
	else:
		label = formatdate(from_date, "MMM YY") + "-" + formatdate(to_date, "MMM YY")

	return label


def get_data(
		company,finance_book,period_list,
		accumulated_values=1, only_current_fiscal_year=True, ignore_closing_entries=False,
		ignore_accumulated_values_for_fy=False , total = True):

	accounts = get_accounts()
	if not accounts:
		return None
	out = prepare_data(accounts, period_list,company,finance_book)
	return out

def prepare_data(accounts, period_list,company,finance_book):
	data = []

	for d in accounts:
		# add to output
		has_value = False
		total = 0
		row = frappe._dict({
			"chi_tieu": d.chi_tieu,
			"ma_so": d.ma_so
		})
		if d.ma_so:
			for period in period_list:

				row[period.key] = get_giatri(period,d.ma_so,period.periodicity,company,finance_book)
				total += row[period.key]


			row["total"] = total
			data.append(row)
			
		else:
			
			for period in period_list:
				
				row[period.key] = ""
				
			data.append(row)

		

	return data

## Hàm tính Nợ - Có của năm có Finance book
def tinhMa60(nam,account,company,finance_book):
    # if finance_book: 
    #     finance_book=finance_book
    # else:
    #     finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
	soTien=0
	for i in account:
		test={
            "nam":nam,
            "account":i,
            "company":company,
            "finance_book":finance_book
   		}
		soTien+=(flt(frappe.db.sql("""
			select
			sum(credit)-sum(debit)
		from `tabGL Entry`
		where
			company=%(company)s
			and (fiscal_year < %(nam)s or ifnull(is_opening, 'No') = 'Yes')
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))
	return soTien

def tinhMa60_Khac_Yearly(nam,account,company,finance_book):
    # if finance_book: 
    #     finance_book=finance_book
    # else:
    #     finance_book=frappe.get_cached_value('Company',company,  "default_finance_book") 
	soTien=0
	for i in account:
		test={
            "nam":nam.from_date.year,
            "account":i,
            "company":company,
            "finance_book":finance_book
  		}
		soTien+= (flt(frappe.db.sql("""
			select
			sum(credit)-sum(debit)
		from `tabGL Entry`
		where
			company=%(company)s
			and (fiscal_year < %(nam)s or ifnull(is_opening, 'No') = 'Yes')
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))
	return soTien

def get_accounts():
	return frappe.db.sql("""
		select chi_tieu, ma_so
		from `tabBang Luu Chuyen Tien Te`
		""",as_dict=True)

def get_columns(periodicity, period_list, accumulated_values=1, company=None):
	columns = [{
		"fieldname": "chi_tieu",
		"label": "Chi Tiêu",
		"fieldtype": "Data",
		"options": "Bang Luu Chuyen Tien Te",
		"width": 400
	},{
		"fieldname": "ma_so",
		"label": "Mã Số",
		"fieldtype": "Data",
		"options": "Bang Luu Chuyen Tien Te",
		"width": 100
	}]

	for period in period_list:
		columns.append({
			"fieldname": period.key,
			"label": period.label,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 200
		})
	if periodicity!="Yearly":
		if not accumulated_values:
			columns.append({
				"fieldname": "total",
				"label": _("Total"),
				"fieldtype": "Currency",
				"width": 200
			})

	return columns

def tinhMa27(nam,company,finance_book):

	account=['5151%','5152%','5153%','5154%','5155%','5156%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['5151','5152','5153','5154','5155','5156']

	return tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)

def tinhMa27_Khac_Yearly(nam,company,finance_book):

	account=['5151%','5152%','5153%','5154%','5155%','5156%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['5151','5152','5153','5154','5155','5156']

	return tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)

def tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book):
	list=[]
	
	for ac in account:
		for ag in against:
			l=layDanhSachTuGLEntryTestTheoMaSoYearly(ac,ag,nam,company)
			list.extend(l)
			
	
	chungTu=[]
	kq=[]

	dem=0

	for i in list:

		if i.voucher_no in chungTu:
			pass
			
		else:
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua=[]

	
	for t in kq:		
		if t.tenTaiKhoanNo in listTKNo:
			if t.tenTaiKhoanCo in listTKCo:
				ketqua.append(t)

	for c in ketqua:
		dem+=c.tienCo+c.tienNo
	return dem

def tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book):
	list=[]
	
	for ac in account:
		for ag in against:
			l=layDanhSachTuGLEntryTestTheoMaSoYearly(ac,ag,nam,company)
			list.extend(l)
			
	
	chungTu=[]
	kq=[]

	dem=0

	for i in list:

		if i.voucher_no in chungTu:
			pass
			
		else:
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua=[]

	
	for t in kq:		
		if t.tenTaiKhoanCo in listTKNo:
			if t.tenTaiKhoanNo in listTKCo:
				ketqua.append(t)

	for c in ketqua:
		dem+=c.tienCo+c.tienNo
	return dem

def tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book):
	list=[]
	
	for ac in account:
		for ag in against:
			l=layDanhSachTuGLEntryTestTheoMaSoKhacYearly(ac,ag,nam,company)
			list.extend(l)
			
	
	chungTu=[]
	kq=[]

	dem=0

	for i in list:

		if i.voucher_no in chungTu:
			pass
			
		else:
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua=[]

	
	for t in kq:		
		if t.tenTaiKhoanCo in listTKNo:
			if t.tenTaiKhoanNo in listTKCo:
				ketqua.append(t)

	for c in ketqua:
		dem+=c.tienCo+c.tienNo
	return dem

def tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book):
	list=[]
	
	for ac in account:
		for ag in against:
			l=layDanhSachTuGLEntryTestTheoMaSoKhacYearly(ac,ag,nam,company)
			list.extend(l)
			
	
	chungTu=[]
	kq=[]

	dem=0

	for i in list:

		if i.voucher_no in chungTu:
			pass
			
		else:
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua=[]

	
	for t in kq:		
		if t.tenTaiKhoanNo in listTKNo:
			if t.tenTaiKhoanCo in listTKCo:
				ketqua.append(t)

	for c in ketqua:
		dem+=c.tienCo+c.tienNo
	return dem

def tinhMa61(nam,company,finance_book):
	list=[]
	list=layDanhSachTuGLEntryTestTheoMaSoYearly('4131%','111%',nam,company)
	list.extend(layDanhSachTuGLEntryTestTheoMaSoYearly('4131%','112%',nam,company))
	list.extend(layDanhSachTuGLEntryTestTheoMaSoYearly('4131%','113%',nam,company))
	list.extend(layDanhSachTuGLEntryTestTheoMaSoYearly('4131%','128%',nam,company))
	chungTu=[]
	kq=[]

	dem=0
	dem2=0

	for i in list:

		if i.voucher_no in chungTu:
			pass
			
		else:
		
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua1=[]
	ketqua2=[]
	soTienWriteOff=0
	soTienWriteOff2=0

	listAccount=['11211','11221','11212','1123','11226','1111','11121','1113','1131','11321',
			'12811','12812','12813','12821','12822','128311','128312','128313','128314','128315','128321',
			'128322','128323','128324','128325','12881','12882','12883']
	for t in kq:		
		if t.tenTaiKhoanNo in listAccount:
			if t.tenTaiKhoanCo=='4131':
				ketqua1.append(t)	
		if t.tenTaiKhoanCo in listAccount:
			if t.tenTaiKhoanNo=='4131':
				ketqua2.append(t)			
		if t.tenTaiKhoanCo=='8111':
			soTienWriteOff+=t.tienCo
		if t.tenTaiKhoanNo=='8111':
			soTienWriteOff2+=t.tienNo

	for c in ketqua1:
		dem+=c.tienNo+c.tienCo

	for c2 in ketqua2:
		dem2+=c2.tienCo

	dem3=dem2-soTienWriteOff2
	return dem-soTienWriteOff-dem3

def tinhMa61_Khac_Yearly(nam,company,finance_book):
	list=[]
	list=layDanhSachTuGLEntryTestTheoMaSoKhacYearly('4131%','111%',nam,company)
	list.extend(layDanhSachTuGLEntryTestTheoMaSoKhacYearly('4131%','112%',nam,company))
	list.extend(layDanhSachTuGLEntryTestTheoMaSoKhacYearly('4131%','113%',nam,company))
	list.extend(layDanhSachTuGLEntryTestTheoMaSoKhacYearly('4131%','128%',nam,company))
	chungTu=[]
	kq=[]

	dem=0
	dem2=0

	for i in list:

		if i.voucher_no in chungTu:
			pass
			
		else:
		
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua1=[]
	ketqua2=[]
	soTienWriteOff=0
	soTienWriteOff2=0

	listAccount=['11211','11221','11212','1123','11226','1111','11121','1113','1131','11321',
			'12811','12812','12813','12821','12822','128311','128312','128313','128314','128315','128321',
			'128322','128323','128324','128325','12881','12882','12883']
	for t in kq:		
		if t.tenTaiKhoanNo in listAccount:
			if t.tenTaiKhoanCo=='4131':
				ketqua1.append(t)	
		if t.tenTaiKhoanCo in listAccount:
			if t.tenTaiKhoanNo=='4131':
				ketqua2.append(t)			
		if t.tenTaiKhoanCo=='8111':
			soTienWriteOff+=t.tienCo
		if t.tenTaiKhoanNo=='8111':
			soTienWriteOff2+=t.tienNo

	for c in ketqua1:
		dem+=c.tienNo+c.tienCo

	for c2 in ketqua2:
		dem2+=c2.tienCo

	dem3=dem2-soTienWriteOff2
	return dem-soTienWriteOff-dem3

def tinhMa2(nam,company,finance_book):
	list=[]
	account=['33111%','33121%','152%','153%','154%','156%']
	against=['111%','112%','113%']
	for i in against:
		for j in account:
			l=layDanhSachTuGLEntryTestTheoMaSoYearly(j,i,nam,company)
			list.extend(l)

	chungTu=[]
	kq=[]
	dem=0

	for i in list:
		if i.voucher_no in chungTu:
			pass			
		else:
			
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua=[]

	listTKCo=['11211','11221','11212','1111','11121','1113','1131','111321']
	listTKNo=['331111','331112','331211','331212','1521','1522','1523','1524','1526','1528','1531',
				'1532','1533','15341','15342','1541','1542','1543','1561','1562','1567']
	for t in kq:		
		if t.tenTaiKhoanCo in listTKCo:
			if t.tenTaiKhoanNo in listTKNo:
				ketqua.append(t)

	for c in ketqua:
		dem+=c.tienCo+c.tienNo
	return dem

def tinhMa2_Khac_Yearly(nam,company,finance_book):
	list=[]
	account=['33111%','33121%','152%','153%','154%','156%']
	against=['111%','112%','113%']
	for i in against:
		for j in account:
			l=layDanhSachTuGLEntryTestTheoMaSoKhacYearly(j,i,nam,company)
			list.extend(l)

	chungTu=[]
	kq=[]
	dem=0

	for i in list:
		if i.voucher_no in chungTu:
			pass			
		else:
			
			for j in phanTichDuLieu(layDSTheoVoucherNo(i.voucher_no)):
				kq.append(j)
			chungTu.append(i.voucher_no)

	ketqua=[]

	listTKCo=['11211','11221','11212','1111','11121','1113','1131','111321']
	listTKNo=['331111','331112','331211','331212','1521','1522','1523','1524','1526','1528','1531',
				'1532','1533','15341','15342','1541','1542','1543','1561','1562','1567']
	for t in kq:		
		if t.tenTaiKhoanCo in listTKCo:
			if t.tenTaiKhoanNo in listTKNo:
				ketqua.append(t)

	for c in ketqua:
		dem+=c.tienCo+c.tienNo
	return dem

def tinhMa1(nam,company,finance_book):
	account=['5111%','5112%','5113%','5114%','5118%','13111%','13121%','5157%','5158%','121%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['5111','5112','5113','5114','5118','131111','131112','131211','131212','5157','5158','1211','1212','1218']
	ketQuaMa1=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa1

def tinhMa1_Khac_Yearly(nam,company,finance_book):
	account=['5111%','5112%','5113%','5114%','5118%','13111%','13121%','5157%','5158%','121%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['5111','5112','5113','5114','5118','131111','131112','131211','131212','5157','5158','1211','1212','1218']
	ketQuaMa1=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa1

def tinhMa3(nam,company,finance_book):
	account=['334%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['3341','3348']
	ketQuaMa3=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa3

def tinhMa3_Khac_Yearly(nam,company,finance_book):
	account=['334%']
	against=['111%','112%','113%']

	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['3341','3348']
	ketQuaMa3=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa3

def tinhMa4(nam,company,finance_book):
	account=['335%','6352%','242%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['3351','33511','33512','33513','33514','33518','33521','33522','33528','6352','24211','24212','24213','24214','24215','24218',
			'24221','24222','24223','24224','24225','24228']
	ketQuaMa4=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa4

def tinhMa4_Khac_Yearly(nam,company,finance_book):

	account=['335%','6352%','242%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['3351','33511','33512','33513','33514','33518','33521','33522','33528','6352','24211','24212','24213','24214','24215','24218',
			'24221','24222','24223','24224','24225','24228']
	ketQuaMa4=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa4

def tinhMa5(nam,company,finance_book):
	account=['3334%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['3334']
	ketQuaMa5=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa5

def tinhMa5_Khac_Yearly(nam,company,finance_book):

	account=['3334%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['3334']
	ketQuaMa5=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa5

def tinhMa6(nam,company,finance_book):
	account=['7111%','7114%','7118%','133%','141%','244%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['7111','7114','7118','133111','133112','133113','133121','133122','133123','133131','133132','133133','1331411','1331412','1331413','1331421','1331422','1331423','13321','13322','1411','1412','2441','2442']
	ketQuaMa6=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa6

def tinhMa6_Khac_Yearly(nam,company,finance_book):
	account=['7111%','7114%','7118%','133%','141%','244%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['7111','7114','7118','133111','133112','133113','133121','133122','133123','133131','133132','133133','1331411','1331412','1331413','1331421','1331422','1331423','13321','13322','1411','1412','2441','2442']
	ketQuaMa6=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa6

def tinhMa7(nam,company,finance_book):
	account=['811%','161%','244%','3331%','3332%','3333%','3335%','3336%','3337%','3338%','3339%','3381%','3382%','3383%','3384%',
			'3385%','3386%','3387%','338811%','338812%','338821%','338822%','344%','352%','353%','356%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['8111','1611','1612','2441','2442','333111','333112','333113','333121','333122','333123',
			'333131','333132','333133','3332','33331','333321','333322','3335','3336','33371','33372','33381','33382','33391','33392','33393',
			'3381','3382','3383','3384','33851','33852','3386','338711','338712','338718','338721','338722','338728','338811','338812','338822',
			'3441','3442','35211','35212','35221','35222','35231','35232','35241','35242','3531','3532','3533','3534','3561','3562']
	ketQuaMa7=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa7


def tinhMa7_Khac_Yearly(nam,company,finance_book):
	account=['811%','161%','244%','3331%','3332%','3333%','3335%','3336%','3337%','3338%','3339%','3381%','3382%','3383%','3384%',
			'3385%','3386%','3387%','338811%','338812%','338821%','338822%','344%','352%','353%','356%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['8111','1611','1612','2441','2442','333111','333112','333113','333121','333122','333123',
			'333131','333132','333133','3332','33331','333321','333322','3335','3336','33371','33372','33381','33382','33391','33392','33393',
			'3381','3382','3383','3384','33851','33852','3386','338711','338712','338718','338721','338722','338728','338811','338812','338822',
			'3441','3442','35211','35212','35221','35222','35231','35232','35241','35242','3531','3532','3533','3534','3561','3562']
	ketQuaMa7=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa7

def tinhMa21(nam,company,finance_book):

	account=['211%','213%','217%','241%','33113%','34112%','33123%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['2111','2112','2113','2114','2115','2118','2131','2132','2133','2134','2135','2136','2138','21711','21712','21713','21714',
			'21721','21722','21723','21724','2411','2412','2413','331131','331132','341121','3411221','331231','331232']
	ketQuaMa21=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa21

def tinhMa21_Khac_Yearly(nam,company,finance_book):

	account=['211%','213%','217%','241%','33113%','34112%','33123%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['2111','2112','2113','2114','2115','2118','2131','2132','2133','2134','2135','2136','2138','21711','21712','21713','21714',
			'21721','21722','21723','21724','2411','2412','2413','331131','331132','341121','3411221','331231','331232']
	ketQuaMa21=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa21

def tinhMa22(nam,company,finance_book):
	account=['7112%','7113%','5117%','13113%','13123%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['7112','7113','5117','131131','131132','131231','131232']
	ketQuaMa22=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa22

def tinhMa22_Khac_Yearly(nam,company,finance_book):
	account=['7112%','7113%','5117%','13113%','13123%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['7112','7113','5117','131131','131132','131231','131232']
	ketQuaMa22=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa22

def tinhMa23(nam,company,finance_book):

	account=['128%','171%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['12811','12812','12813','12821','12822','128311','128312','128313','128314','128315','128321'
			'128322','128323','128324','128325','12881','12882','12883','1711']
	ketQuaMa23=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa23

def tinhMa23_Khac_Yearly(nam,company,finance_book):

	account=['128%','171%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['12811','12812','12813','12821','12822','128311','128312','128313','128314','128315','128321'
			'128322','128323','128324','128325','12881','12882','12883','1711']
	ketQuaMa23=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa23

def tinhMa24(nam,company,finance_book):
	account=['128%','171%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['12811','12812','12813','12821','12822','128311','128312','128313','128314','128315','128321'
			'128322','128323','128324','128325','12881','12882','12883','1711']
	ketQuaMa24=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa24

def tinhMa24_Khac_Yealy(nam,company,finance_book):
	account=['128%','171%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['12811','12812','12813','12821','12822','128311','128312','128313','128314','128315','128321'
			'128322','128323','128324','128325','12881','12882','12883','1711']
	ketQuaMa24=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa24

def tinhMa25(nam,company,finance_book):

	account=['221%','222%','2281%','33112%','33122%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['2211','2221','2281','331121','331122','331221',]
	ketQuaMa25=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa25

def tinhMa25_Khac_Yearly(nam,company,finance_book):

	account=['221%','222%','2281%','33112%','33122%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['2211','2221','2281','331121','331122','331221',]
	ketQuaMa25=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa25


def tinhMa26(nam,company,finance_book):

	account=['221%','222%','2281%','13112%','13122%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['2211','2221','2281','131121','131122','131221','131222']
	ketQuaMa26=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa26

def tinhMa26_Khac_Yearly(nam,company,finance_book):

	account=['221%','222%','2281%','13112%','13122%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['2211','2221','2281','131121','131122','131221','131222']
	ketQuaMa26=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa26

def tinhMa31(nam,company,finance_book):
	account=['411111%','419%','411112%','411121%','4112%','4113%','4118%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['411111','411112','411121','4112','4113','4118','4191']
	ketQuaMa31=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa31

def tinhMa31_Khac_Yearly(nam,company,finance_book):
	account=['411111%','419%','411112%','411121%','4112%','4113%','4118%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['411111','411112','411121','4112','4113','4118','4191']
	ketQuaMa31=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa31

def tinhMa32(nam,company,finance_book):
	account=['411111%','419%','411112%','411121%','4112%','4113%','4118%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['411111','411112','411121','4112','4113','4118','4191']
	ketQuaMa32=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa32

def tinhMa32_Khac_Yearly(nam,company,finance_book):
	account=['411111%','419%','411112%','411121%','4112%','4113%','4118%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['411111','411112','411121','4112','4113','4118','4191']
	ketQuaMa32=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa32

def tinhMa33(nam,company,finance_book):

	account=['34111%','3431%','3432%','411122%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['341111','343111','343112','34312','34313','3432','411122']
	ketQuaMa33=tinhKetQuaBenCo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa33

def tinhMa33_Khac_Yearly(nam,company,finance_book):

	account=['34111%','3431%','3432%','411122%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['341111','343111','343112','34312','34313','3432','411122']
	ketQuaMa33=tinhKetQuaBenCo_Khac_Yealy(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa33

def tinhMa34(nam,company,finance_book):
	account=['34111%','3431%','3432%','411122%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['341111','343111','343112','34312','34313','3432','411122']
	ketQuaMa34=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa34

def tinhMa34_Khac_Yearly(nam,company,finance_book):
	account=['34111%','3431%','3432%','411122%']
	against=['111%','112%','113%']
	
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['341111','343111','343112','34312','34313','3432','411122']
	ketQuaMa34=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa34
	
def tinhMa35(nam,company,finance_book):

	account=['3412%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['341211','3412121','341221','3412221']
	ketQuaMa35=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa35

def tinhMa35_Khac_Yearly(nam,company,finance_book):

	account=['3412%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['341211','3412121','341221','3412221']
	ketQuaMa35=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa35

def tinhMa36(nam,company,finance_book):
	account=['421%','338813%','338823%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['4211','4212','338813','338823']
	ketQuaMa36=tinhKetQuaBenNo(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa36

def tinhMa36_Khac_Yearly(nam,company,finance_book):
	account=['421%','338813%','338823%']
	against=['111%','112%','113%']
	listTKNo=['11211','11221','11212','1111','11121','1113','1131','11321']
	listTKCo=['4211','4212','338813','338823']
	ketQuaMa36=tinhKetQuaBenNo_Khac_Yearly(account,against,listTKNo,listTKCo,nam,company,finance_book)
	return ketQuaMa36
	
def get_giatri(nam,maso,periodicity,company,finance_book):
	if periodicity=="Yearly":		

		nam=nam.label

		if maso=='1':		
			return tinhMa1(nam,company,finance_book)
		elif maso=='2':		
			return -tinhMa2(nam,company,finance_book)
		elif maso=='3':		
			return -tinhMa3(nam,company,finance_book)
		elif maso=='4':		
			return -tinhMa4(nam,company,finance_book)
		elif maso=='5':
			return -tinhMa5(nam,company,finance_book)
		elif maso=='6':		
			return tinhMa6(nam,company,finance_book)		
		elif maso=='7':
			return -tinhMa7(nam,company,finance_book)
		elif maso=='20':
			return (
				tinhMa1(nam,company,finance_book)
				-tinhMa2(nam,company,finance_book)
				-tinhMa3(nam,company,finance_book)
				-tinhMa4(nam,company,finance_book)
				-tinhMa5(nam,company,finance_book)
				+tinhMa6(nam,company,finance_book)
				-tinhMa7(nam,company,finance_book)
			)
		elif maso == '21':
			return -tinhMa21(nam,company,finance_book)		
		elif maso == '22':
			return tinhMa22(nam,company,finance_book)
		elif maso == '23':
			return -tinhMa23(nam,company,finance_book)
		elif maso == '24':
			return tinhMa24(nam,company,finance_book)
		elif maso == '25':
			return -tinhMa25(nam,company,finance_book)
		elif maso == '26':
			return tinhMa26(nam,company,finance_book)
		elif maso == '27':
			return tinhMa27(nam,company,finance_book)
		elif maso == '30':
			return (
				-tinhMa21(nam,company,finance_book)
				+tinhMa22(nam,company,finance_book)
				-tinhMa23(nam,company,finance_book)
				+tinhMa24(nam,company,finance_book)
				-tinhMa25(nam,company,finance_book)
				+tinhMa26(nam,company,finance_book)
				+tinhMa27(nam,company,finance_book)
			)
		elif maso=='31':
			return tinhMa31(nam,company,finance_book)
		elif maso=='32':
			return -tinhMa32(nam,company,finance_book) 
		elif maso=='33':
			return tinhMa33(nam,company,finance_book)
		elif maso=='34':
			return -tinhMa34(nam,company,finance_book) 
		elif maso=='35':
			return -tinhMa35(nam,company,finance_book) 
		elif maso=='36':
			return tinhMa36(nam,company,finance_book)
		elif maso=='40':
			return (
				tinhMa31(nam,company,finance_book)
				-tinhMa32(nam,company,finance_book)
				+tinhMa33(nam,company,finance_book)
				-tinhMa34(nam,company,finance_book)
				-tinhMa35(nam,company,finance_book)
				+tinhMa36(nam,company,finance_book)
			)
		elif maso =='50':
			return (tinhMa1(nam,company,finance_book)
				-tinhMa2(nam,company,finance_book)
				-tinhMa3(nam,company,finance_book)
				-tinhMa4(nam,company,finance_book)
				-tinhMa5(nam,company,finance_book)
				+tinhMa6(nam,company,finance_book)
				-tinhMa7(nam,company,finance_book)
				-tinhMa21(nam,company,finance_book)
				+tinhMa22(nam,company,finance_book)
				-tinhMa23(nam,company,finance_book)
				+tinhMa24(nam,company,finance_book)
				-tinhMa25(nam,company,finance_book)
				+tinhMa26(nam,company,finance_book)
				+tinhMa27(nam,company,finance_book)
				+tinhMa31(nam,company,finance_book)
				-tinhMa32(nam,company,finance_book)
				+tinhMa33(nam,company,finance_book)
				-tinhMa34(nam,company,finance_book)
				-tinhMa35(nam,company,finance_book)
				+tinhMa36(nam,company,finance_book)
				)
		elif maso== '60':
			return -(tinhMa60(nam,['111%%','112%','113%','12811%','12881%'],company,finance_book))
		elif maso== '61':
			return tinhMa61(nam,company,finance_book)
		elif maso== '70':
			return (tinhMa1(nam,company,finance_book)
				-tinhMa2(nam,company,finance_book)
				-tinhMa3(nam,company,finance_book)
				-tinhMa4(nam,company,finance_book)
				-tinhMa5(nam,company,finance_book)
				+tinhMa6(nam,company,finance_book)
				-tinhMa7(nam,company,finance_book)
				-tinhMa21(nam,company,finance_book)
				+tinhMa22(nam,company,finance_book)
				-tinhMa23(nam,company,finance_book)
				+tinhMa24(nam,company,finance_book)
				-tinhMa25(nam,company,finance_book)
				+tinhMa26(nam,company,finance_book)
				+tinhMa27(nam,company,finance_book)
				+tinhMa31(nam,company,finance_book)
				-tinhMa32(nam,company,finance_book)
				+tinhMa33(nam,company,finance_book)
				-tinhMa34(nam,company,finance_book)
				-tinhMa35(nam,company,finance_book)
				+tinhMa36(nam,company,finance_book)
				-(tinhMa60(nam,['111%%','112%','113%','12811%','12881%'],company,finance_book))
				+tinhMa61(nam,company,finance_book)
				)
	else:

		ketQuaMa60=0
		if nam.from_date.month==1:
			ketQuaMa60=-(tinhMa60_Khac_Yearly(nam,['111%%','112%','113%','12811%','12881%'],company,finance_book))
		
		if maso=='1':		
			return tinhMa1_Khac_Yearly(nam,company,finance_book)
		elif maso=='2':
			return -tinhMa2_Khac_Yearly(nam,company,finance_book)
		elif maso=='3':
			return -tinhMa3_Khac_Yearly(nam,company,finance_book)
		elif maso=='4':
			return -tinhMa4_Khac_Yearly(nam,company,finance_book)
		elif maso=='5':
			return -tinhMa5_Khac_Yearly(nam,company,finance_book)
		elif maso=='6':
			return tinhMa6_Khac_Yearly(nam,company,finance_book)
		elif maso=='7':
			return -tinhMa7_Khac_Yearly(nam,company,finance_book)
		elif maso=='20':
			return (
				tinhMa1_Khac_Yearly(nam,company,finance_book)
				-tinhMa2_Khac_Yearly(nam,company,finance_book)
				-tinhMa3_Khac_Yearly(nam,company,finance_book)
				-tinhMa4_Khac_Yearly(nam,company,finance_book)
				-tinhMa5_Khac_Yearly(nam,company,finance_book)
				+tinhMa6_Khac_Yearly(nam,company,finance_book)
				-tinhMa7_Khac_Yearly(nam,company,finance_book)
			)
		elif maso == '21':
			return -tinhMa21_Khac_Yearly(nam,company,finance_book)		
		elif maso == '22':
			return tinhMa22_Khac_Yearly(nam,company,finance_book)
		elif maso == '23':
			return -tinhMa23_Khac_Yearly(nam,company,finance_book)
		elif maso == '24':
			return tinhMa24_Khac_Yealy(nam,company,finance_book)
		elif maso == '25':
			return -tinhMa25_Khac_Yearly(nam,company,finance_book)
		elif maso == '26':
			return tinhMa26_Khac_Yearly(nam,company,finance_book)
		elif maso == '27':
			return tinhMa27_Khac_Yearly(nam,company,finance_book)
		elif maso == '30':
			return (
				-tinhMa21_Khac_Yearly(nam,company,finance_book)
				+tinhMa22_Khac_Yearly(nam,company,finance_book)
				-tinhMa23_Khac_Yearly(nam,company,finance_book)
				+tinhMa24_Khac_Yealy(nam,company,finance_book)
				-tinhMa25_Khac_Yearly(nam,company,finance_book)
				+tinhMa26_Khac_Yearly(nam,company,finance_book)
				+tinhMa27_Khac_Yearly(nam,company,finance_book)
			)
		elif maso=='31':
			return tinhMa31_Khac_Yearly(nam,company,finance_book)
		elif maso=='32':
			return -tinhMa32_Khac_Yearly(nam,company,finance_book) 
		elif maso=='33':
			return tinhMa33_Khac_Yearly(nam,company,finance_book)
		elif maso=='34':
			return -tinhMa34_Khac_Yearly(nam,company,finance_book) 
		elif maso=='35':
			return -tinhMa35_Khac_Yearly(nam,company,finance_book) 
		elif maso=='36':
			return tinhMa36_Khac_Yearly(nam,company,finance_book)
		elif maso=='40':
			return (
				tinhMa31_Khac_Yearly(nam,company,finance_book)
				-tinhMa32_Khac_Yearly(nam,company,finance_book)
				+tinhMa33_Khac_Yearly(nam,company,finance_book)
				-tinhMa34_Khac_Yearly(nam,company,finance_book)
				-tinhMa35_Khac_Yearly(nam,company,finance_book)
				+tinhMa36_Khac_Yearly(nam,company,finance_book)
			)
		elif maso =='50':
			return (
				tinhMa1_Khac_Yearly(nam,company,finance_book)
				-tinhMa2_Khac_Yearly(nam,company,finance_book)
				-tinhMa3_Khac_Yearly(nam,company,finance_book)
				-tinhMa4_Khac_Yearly(nam,company,finance_book)
				-tinhMa5_Khac_Yearly(nam,company,finance_book)
				+tinhMa6_Khac_Yearly(nam,company,finance_book)
				-tinhMa7_Khac_Yearly(nam,company,finance_book)
				-tinhMa21_Khac_Yearly(nam,company,finance_book)
				+tinhMa22_Khac_Yearly(nam,company,finance_book)
				-tinhMa23_Khac_Yearly(nam,company,finance_book)
				+tinhMa24_Khac_Yealy(nam,company,finance_book)
				-tinhMa25_Khac_Yearly(nam,company,finance_book)
				+tinhMa26_Khac_Yearly(nam,company,finance_book)
				+tinhMa27_Khac_Yearly(nam,company,finance_book)
				+tinhMa31_Khac_Yearly(nam,company,finance_book)
				-tinhMa32_Khac_Yearly(nam,company,finance_book)
				+tinhMa33_Khac_Yearly(nam,company,finance_book)
				-tinhMa34_Khac_Yearly(nam,company,finance_book)
				-tinhMa35_Khac_Yearly(nam,company,finance_book)
				+tinhMa36_Khac_Yearly(nam,company,finance_book)
			)
		elif maso== '60':
			return ketQuaMa60
		elif maso== '61':
			return tinhMa61_Khac_Yearly(nam,company,finance_book)
		elif maso== '70':
			return (
				tinhMa1_Khac_Yearly(nam,company,finance_book)
				-tinhMa2_Khac_Yearly(nam,company,finance_book)
				-tinhMa3_Khac_Yearly(nam,company,finance_book)
				-tinhMa4_Khac_Yearly(nam,company,finance_book)
				-tinhMa5_Khac_Yearly(nam,company,finance_book)
				+tinhMa6_Khac_Yearly(nam,company,finance_book)
				-tinhMa7_Khac_Yearly(nam,company,finance_book)
				-tinhMa21_Khac_Yearly(nam,company,finance_book)
				+tinhMa22_Khac_Yearly(nam,company,finance_book)
				-tinhMa23_Khac_Yearly(nam,company,finance_book)
				+tinhMa24_Khac_Yealy(nam,company,finance_book)
				-tinhMa25_Khac_Yearly(nam,company,finance_book)
				+tinhMa26_Khac_Yearly(nam,company,finance_book)
				+tinhMa27_Khac_Yearly(nam,company,finance_book)
				+tinhMa31_Khac_Yearly(nam,company,finance_book)
				-tinhMa32_Khac_Yearly(nam,company,finance_book)
				+tinhMa33_Khac_Yearly(nam,company,finance_book)
				-tinhMa34_Khac_Yearly(nam,company,finance_book)
				-tinhMa35_Khac_Yearly(nam,company,finance_book)
				+tinhMa36_Khac_Yearly(nam,company,finance_book)
				+ketQuaMa60
				+tinhMa61_Khac_Yearly(nam,company,finance_book)
					)
		

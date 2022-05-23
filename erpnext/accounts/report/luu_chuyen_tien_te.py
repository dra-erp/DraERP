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
	def __init__(self, tenTaiKhoanCo,tenTaiKhoanNo, tienCo,tienNo):
		self.tenTaiKhoanCo = tenTaiKhoanCo
		self.tienCo = tienCo
		self.tenTaiKhoanNo = tenTaiKhoanNo
		self.tienNo = tienNo
class DinhKhoan(TaiKhoan):
	def __init__(self):
		TaiKhoan.__init__(self)
def layDanhSachTuGLEntry(nam,company):
	input={
		nam:nam,
		company:company
	}
	return frappe.db.sql("""
		select posting_date,voucher_no,account,debit,credit
		from `GL Entry` where fiscal_year=%(nam)s and company=%(company)s
		""",as_dict=True)
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
				#total += row[period.key]


			row["total"] = total
			data.append(row)
			
		else:
			
			for period in period_list:
				
				row[period.key] = ""
				
			data.append(row)

		

	return data
def tinh_Opening_Cua_Ma_110_Yearly(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	
	temp= flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date<%(nam)s
			""",test,as_list=True)[0][0],2)
	if temp:
		return temp
	else:
		return 0
def tinh_credit(nam,account,against,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"against": against,
		"company":company,
		"finance_book":finance_book
	}
	temp =  flt(frappe.db.sql("""				
		
select IFNULL((SELECT if(party IS NULL,(
	SELECT SUM(credit) FROM `tabGL Entry`  
	WHERE ACCOUNT LIKE %(account)s 
		AND AGAINST LIKE %(against)s 
		AND fiscal_year=%(nam)s 
		AND is_cancelled=0 AND company = %(company)s
	OR ACCOUNT LIKE %(account)s 
		AND AGAINST IN 
			(SELECT party 
			FROM `tabGL Entry` 
			WHERE ACCOUNT LIKE %(against)s 
				AND AGAINST LIKE %(account)s) 
				AND fiscal_year=%(nam)s AND is_cancelled=0 AND company = %(company)s
		),(
	SELECT SUM(debit) FROM `tabGL Entry`  
	WHERE ACCOUNT LIKE %(against)s 
		AND AGAINST LIKE %(account)s 
		AND fiscal_year=%(nam)s 
		AND is_cancelled=0 AND company = %(company)s
	OR ACCOUNT LIKE %(against)s 
		AND AGAINST IN 
			(SELECT party 
			FROM `tabGL Entry` 
			WHERE ACCOUNT LIKE %(account)s 
				AND AGAINST LIKE %(against)s) 
				AND fiscal_year=%(nam)s AND is_cancelled=0 AND company = %(company)s
		)) AS soTien FROM `tabGL Entry` 
				WHERE company = %(company)s AND is_cancelled=0 AND fiscal_year=%(nam)s
				GROUP BY soTien HAVING soTien>0 order by soTien LIMIT 1),0) AS soTien;


	""",test,as_list=True)[0][0],2)
	
	if temp:
		return temp
	else:
		return 0
def tinh_debit(nam,account,against,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"against": against,
		"company":company,
		"finance_book":finance_book
	}
	temp =  flt(frappe.db.sql("""
		
		
select IFNULL((SELECT if(party IS NULL,(
	SELECT SUM(debit) FROM `tabGL Entry`  
	WHERE ACCOUNT LIKE %(account)s 
		AND AGAINST LIKE %(against)s 
		AND fiscal_year=%(nam)s 
		AND is_cancelled=0 AND company = %(company)s
	OR ACCOUNT LIKE %(account)s 
		AND AGAINST IN 
			(SELECT party 
			FROM `tabGL Entry` 
			WHERE ACCOUNT LIKE %(against)s 
				AND AGAINST LIKE %(account)s) 
				AND fiscal_year=%(nam)s AND is_cancelled=0 AND company = %(company)s
		OR (ACCOUNT LIKE %(account)s AND voucher_no IN
			(SELECT voucher_no 
			FROM `tabGL Entry` 
			WHERE AGAINST LIKE %(against)s 
				AND credit=0) 
				AND fiscal_year=%(nam)s 
				AND is_cancelled=0 AND company = %(company)s)),(
	SELECT SUM(credit) FROM `tabGL Entry`  
	WHERE ACCOUNT LIKE %(against)s 
		AND AGAINST LIKE %(account)s 
		AND fiscal_year=%(nam)s 
		AND is_cancelled=0 AND company = %(company)s
	OR ACCOUNT LIKE %(against)s 
		AND AGAINST IN 
			(SELECT party 
			FROM `tabGL Entry` 
			WHERE ACCOUNT LIKE %(account)s 
				AND AGAINST LIKE %(against)s) 
				AND fiscal_year=%(nam)s AND is_cancelled=0 AND company = %(company)s
		OR (ACCOUNT LIKE %(against)s AND voucher_no IN
			(SELECT voucher_no 
			FROM `tabGL Entry` 
			WHERE AGAINST LIKE %(account)s 
				AND credit=0) 
				AND fiscal_year=%(nam)s 
				AND is_cancelled=0 AND company = %(company)s))) AS soTien FROM `tabGL Entry`
				WHERE company = %(company)s AND is_cancelled=0 AND fiscal_year=%(nam)s
				GROUP BY soTien HAVING soTien>0 order by soTien LIMIT 1),0) AS soTien;
	""",test,as_list=True)[0][0],2)
	
	if temp:
		return temp
	else:
		return 0

def tinh_Opening_Cua_Ma_110_Khac_Yearly(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	
	temp= flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date<%(nam)s
			""",test,as_list=True)[0][0],2)
	if temp:
		return temp
	else:
		return 0
def tinh_credit_Khac_Yearly(nam,account,against,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"against": against,
		"company":company,
		"finance_book":finance_book
	}
	
	
	temp =  flt(frappe.db.sql("""
	SELECT IF(party is NULL,(select SUM(credit) FROM `tabGL Entry` WHERE ACCOUNT LIKE %(account)s AND AGAINST IN (
    	SELECT party FROM `tabGL Entry` WHERE ACCOUNT LIKE %(against)s AND AGAINST LIKE %(account)s) and is_cancelled=0 and posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s
      		OR  ACCOUNT LIKE %(account)s AND AGAINST LIKE %(against)s and is_cancelled=0 and posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s),(select SUM(debit) FROM `tabGL Entry` WHERE ACCOUNT LIKE %(against)s AND AGAINST IN (
        		SELECT party FROM `tabGL Entry` WHERE ACCOUNT LIKE %(account)s AND AGAINST LIKE %(against)s) and is_cancelled=0 and posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s
          			OR  ACCOUNT LIKE %(against)s AND AGAINST LIKE %(account)s and is_cancelled=0 and posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s))AS test FROM `tabGL Entry` ORDER BY test LIMIT 1""",test,as_list=True)[0][0],2)

	if temp:
		return temp
	else:
		return 0
def tinh_debit_Khac_Yearly(nam,account,against,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"against": against,
		"company":company,
		"finance_book":finance_book
	}
	temp =  flt(frappe.db.sql("""
	SELECT IF(party is NULL,(select SUM(debit) FROM `tabGL Entry` WHERE against LIKE %(against)s AND account IN (
    	SELECT party FROM `tabGL Entry` WHERE against LIKE %(account)s AND account LIKE %(against)s) and is_cancelled=0 AND posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s
      		OR  against LIKE %(against)s AND account LIKE %(account)s and is_cancelled=0 AND posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s),(select SUM(credit) FROM `tabGL Entry` WHERE against LIKE %(account)s AND account IN (
        		SELECT party FROM `tabGL Entry` WHERE against LIKE %(against)s AND account LIKE %(account)s) and is_cancelled=0 AND posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s
          			OR  against LIKE %(account)s AND account LIKE %(against)s and is_cancelled=0 AND posting_date >=  %(from_date)s 
			and posting_date <=  %(to_date)s))AS test FROM `tabGL Entry` ORDER BY test LIMIT 1""",test,as_list=True)[0][0],2)
	
	if temp:
		return temp
	else:
		return 0

def get_accounts():
	return frappe.db.sql("""
		select chi_tieu, ma_so
		from `tabBang Luu Chuyen Tien Te`
		""",as_dict=True)

def get_columns(periodicity, period_list, accumulated_values=1, company=None):
	columns = [{
		"fieldname": "chi_tieu",
		"label": "Chi Tieu",
		"fieldtype": "Data",
		"options": "Bang Luu Chuyen Tien Te",
		"width": 400
	},{
		"fieldname": "ma_so",
		"label": "Ma So",
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
			"width": 250
		})
	if periodicity!="Yearly":
		if not accumulated_values:
			columns.append({
				"fieldname": "total",
				"label": _("Total"),
				"fieldtype": "Currency",
				"width": 150
			})

	return columns

def get_giatri(nam,maso,periodicity,company,finance_book):
	if periodicity=="Yearly":		
		from_date=nam.from_date
		nam=nam.label
		if maso=='1':			
			return (tinh_credit(nam,'5111%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5111%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5111%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'113%%',company,finance_book))
		elif maso=='2':
			return -(tinh_debit(nam,'33111%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'33111%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'33111%%' ,'113%%',company,finance_book) 
					+tinh_debit(nam,'33121%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'33121%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'33121%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'113%%',company,finance_book))
		elif maso=='3':
			return -(tinh_debit(nam,'334%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'334%%' ,'112%%',company,finance_book) )
		elif maso=='4':
			return -(tinh_debit(nam,'335%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'335%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'335%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'6352%%' ,'111%%',company,finance_book)  
					+ tinh_debit(nam,'6352%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'6352%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'113%%',company,finance_book))
		elif maso=='5':
			return (tinh_debit(nam,'3334%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3334%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3334%%', '113%%',company,finance_book))
		elif maso=='6':
			return (tinh_credit(nam,'7111%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7111%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7111%%', '113%%',company,finance_book) 
			+tinh_credit(nam,'7114%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7114%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7114%%', '113%%',company,finance_book) 
			+tinh_credit(nam,'7118%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7118%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7118%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '113%%',company,finance_book))
		elif maso=='7':
			return -(tinh_debit(nam,'811%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'811%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'811%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '113%%',company,finance_book))
		elif maso=='20':
			return ((tinh_credit(nam,'5111%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5111%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5111%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'113%%',company,finance_book))
		 -(tinh_debit(nam,'33111%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'33111%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'33111%%' ,'113%%',company,finance_book) 
					+tinh_debit(nam,'33121%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'33121%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'33121%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'113%%',company,finance_book))
		-(tinh_debit(nam,'334%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'334%%' ,'112%%',company,finance_book) )
		-(tinh_debit(nam,'335%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'335%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'335%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'6352%%' ,'111%%',company,finance_book)  
					+ tinh_debit(nam,'6352%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'6352%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'113%%',company,finance_book))
		+(tinh_debit(nam,'3334%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3334%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3334%%', '113%%',company,finance_book))
		+(tinh_credit(nam,'7111%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7111%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7111%%', '113%%',company,finance_book) 
			+tinh_credit(nam,'7114%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7114%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7114%%', '113%%',company,finance_book) 
			+tinh_credit(nam,'7118%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7118%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7118%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '113%%',company,finance_book))
		-(tinh_debit(nam,'811%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'811%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'811%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '113%%',company,finance_book)))
		elif maso == '21':
			return -(tinh_debit(nam,'211%','111%%',company,finance_book) 
			+ tinh_debit(nam,'211%','112%%',company,finance_book) 
			+tinh_debit(nam,'211%','113%%',company,finance_book) 
			+ tinh_debit(nam,'213%','111%%',company,finance_book) 
			+ tinh_debit(nam,'213%','112%%',company,finance_book) 
			+tinh_debit(nam,'213%','113%%',company,finance_book) 
			+ tinh_debit(nam,'217%','111%%',company,finance_book) 
			+ tinh_debit(nam,'217%','112%%',company,finance_book) 
			+tinh_debit(nam,'217%','113%%',company,finance_book) 
			+ tinh_debit(nam,'241%','111%%',company,finance_book) 
			+ tinh_debit(nam,'241%','112%%',company,finance_book) 
			+tinh_debit(nam,'241%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33113%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33113%','112%%',company,finance_book) 
			+tinh_debit(nam,'33113%','113%%',company,finance_book) 
			+ tinh_debit(nam,'34112%','111%%',company,finance_book) 
			+ tinh_debit(nam,'34112%','112%%',company,finance_book) 
			+tinh_debit(nam,'34112%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33123%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33123%','112%%',company,finance_book) 
			+tinh_debit(nam,'33123%','113%%',company,finance_book) )
		elif maso == '22':
			return (tinh_credit(nam,'7112%','111%%',company,finance_book) 
			+ tinh_credit(nam,'7112%','112%%',company,finance_book) 
			+tinh_credit(nam,'7112%','113%%',company,finance_book) 
			+ tinh_credit(nam,'7113%','111%%',company,finance_book) 
			+ tinh_credit(nam,'7113%','112%%',company,finance_book) 
			+tinh_credit(nam,'7113%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5117%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5117%','112%%',company,finance_book) 
			+tinh_credit(nam,'5117%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13113%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13113%','112%%',company,finance_book) 
			+tinh_credit(nam,'13113%','113%%',company,finance_book) 
			+ tinh_credit(nam,'13123%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13123%','112%%',company,finance_book) 
			+tinh_credit(nam,'13123%','113%%',company,finance_book) )
		elif maso == '23':
			return -(tinh_debit(nam,'128%','111%%',company,finance_book) 
			+ tinh_debit(nam,'128%','112%%',company,finance_book) 
			+ tinh_debit(nam,'128%','113%%',company,finance_book) 
			+ tinh_debit(nam,'171%','111%%',company,finance_book) 
			+ tinh_debit(nam,'171%','112%%',company,finance_book) 
			+ tinh_debit(nam,'171%','113%%',company,finance_book) )
		elif maso == '24':
			return (tinh_credit(nam,'128%','111%%',company,finance_book) 
			+ tinh_credit(nam,'128%','112%%',company,finance_book) 
			+ tinh_credit(nam,'128%','113%%',company,finance_book) 
			+tinh_credit(nam,'171%','111%%',company,finance_book) 
			+ tinh_credit(nam,'171%','112%%',company,finance_book) 
			+ tinh_credit(nam,'171%','113%%',company,finance_book))
		elif maso == '25':
			return -(tinh_debit(nam,'221%','111%%',company,finance_book) 
			+ tinh_debit(nam,'221%','112%%',company,finance_book) 
			+ tinh_debit(nam,'221%','113%%',company,finance_book) 
			+ tinh_debit(nam,'222%','111%%',company,finance_book) 
			+ tinh_debit(nam,'222%','112%%',company,finance_book) 
			+ tinh_debit(nam,'222%','113%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','111%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','112%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','112%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','112%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','113%%',company,finance_book))
		elif maso == '26':
			return (tinh_credit(nam,'221%','111%%',company,finance_book) 
			+ tinh_credit(nam,'221%','112%%',company,finance_book) 
			+ tinh_credit(nam,'221%','113%%',company,finance_book) 
			+ tinh_credit(nam,'222%','111%%',company,finance_book) 
			+ tinh_credit(nam,'222%','112%%',company,finance_book) 
			+ tinh_credit(nam,'222%','113%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','111%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','112%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13112%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13112%','112%%',company,finance_book) 
			+ tinh_credit(nam,'13112%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13122%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13122%','112%%',company,finance_book) 
			+ tinh_credit(nam,'13122%','113%%',company,finance_book))
		elif maso == '27':
			return  (tinh_credit(nam,'5151%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5151%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5151%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','113%%',company,finance_book) 
			+  tinh_credit(nam,'5156%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5156%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5156%','113%%',company,finance_book) )
		elif maso == '30':
			return (-(tinh_debit(nam,'211%','111%%',company,finance_book) 
			+ tinh_debit(nam,'211%','112%%',company,finance_book) 
			+tinh_debit(nam,'211%','113%%',company,finance_book) 
			+ tinh_debit(nam,'213%','111%%',company,finance_book) 
			+ tinh_debit(nam,'213%','112%%',company,finance_book) 
			+tinh_debit(nam,'213%','113%%',company,finance_book) 
			+ tinh_debit(nam,'217%','111%%',company,finance_book) 
			+ tinh_debit(nam,'217%','112%%',company,finance_book) 
			+tinh_debit(nam,'217%','113%%',company,finance_book) 
			+ tinh_debit(nam,'241%','111%%',company,finance_book) 
			+ tinh_debit(nam,'241%','112%%',company,finance_book) 
			+tinh_debit(nam,'241%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33113%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33113%','112%%',company,finance_book) 
			+tinh_debit(nam,'33113%','113%%',company,finance_book) 
			+ tinh_debit(nam,'34112%','111%%',company,finance_book) 
			+ tinh_debit(nam,'34112%','112%%',company,finance_book) 
			+tinh_debit(nam,'34112%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33123%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33123%','112%%',company,finance_book) 
			+tinh_debit(nam,'33123%','113%%',company,finance_book) )
		+(tinh_credit(nam,'7112%','111%%',company,finance_book) 
			+ tinh_credit(nam,'7112%','112%%',company,finance_book) 
			+tinh_credit(nam,'7112%','113%%',company,finance_book) 
			+ tinh_credit(nam,'7113%','111%%',company,finance_book) 
			+ tinh_credit(nam,'7113%','112%%',company,finance_book) 
			+tinh_credit(nam,'7113%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5117%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5117%','112%%',company,finance_book) 
			+tinh_credit(nam,'5117%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13113%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13113%','112%%',company,finance_book) 
			+tinh_credit(nam,'13113%','113%%',company,finance_book) 
			+ tinh_credit(nam,'13123%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13123%','112%%',company,finance_book) 
			+tinh_credit(nam,'13123%','113%%',company,finance_book) )
		-(tinh_debit(nam,'128%','111%%',company,finance_book) 
			+ tinh_debit(nam,'128%','112%%',company,finance_book) 
			+ tinh_debit(nam,'128%','113%%',company,finance_book) 
			+ tinh_debit(nam,'171%','111%%',company,finance_book) 
			+ tinh_debit(nam,'171%','112%%',company,finance_book) 
			+ tinh_debit(nam,'171%','113%%',company,finance_book) )
		+(tinh_credit(nam,'128%','111%%',company,finance_book) 
			+ tinh_credit(nam,'128%','112%%',company,finance_book) 
			+ tinh_credit(nam,'128%','113%%',company,finance_book) 
			+tinh_credit(nam,'171%','111%%',company,finance_book) 
			+ tinh_credit(nam,'171%','112%%',company,finance_book) 
			+ tinh_credit(nam,'171%','113%%',company,finance_book))
		-(tinh_debit(nam,'221%','111%%',company,finance_book) 
			+ tinh_debit(nam,'221%','112%%',company,finance_book) 
			+ tinh_debit(nam,'221%','113%%',company,finance_book) 
			+ tinh_debit(nam,'222%','111%%',company,finance_book) 
			+ tinh_debit(nam,'222%','112%%',company,finance_book) 
			+ tinh_debit(nam,'222%','113%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','111%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','112%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','112%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','112%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','113%%',company,finance_book))
		+(tinh_credit(nam,'221%','111%%',company,finance_book) 
			+ tinh_credit(nam,'221%','112%%',company,finance_book) 
			+ tinh_credit(nam,'221%','113%%',company,finance_book) 
			+ tinh_credit(nam,'222%','111%%',company,finance_book) 
			+ tinh_credit(nam,'222%','112%%',company,finance_book) 
			+ tinh_credit(nam,'222%','113%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','111%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','112%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13112%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13112%','112%%',company,finance_book) 
			+ tinh_credit(nam,'13112%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13122%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13122%','112%%',company,finance_book) 
			+ tinh_credit(nam,'13122%','113%%',company,finance_book))
		+(tinh_credit(nam,'5151%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5151%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5151%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','113%%',company,finance_book) 
			+  tinh_credit(nam,'5156%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5156%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5156%','113%%',company,finance_book) ))
		elif maso=='31':
			return (tinh_credit(nam, '411111%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411111%%' , '112%%',company,finance_book)
			+ tinh_credit(nam, '411111%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4118%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4118%%' , '112%%',company,finance_book)
			+ tinh_credit(nam, '4118%%' , '113%%',company,finance_book))
		elif maso=='32':
			return -(tinh_debit(nam, '411111%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411111%%' , '112%%',company,finance_book)
			+ tinh_debit(nam, '411111%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '113%%',company,finance_book))
		elif maso=='33':
			return (tinh_credit(nam,'3411%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3411%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3411%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '113%%',company,finance_book))
		elif maso=='34':
			return -(tinh_debit(nam,'34111%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'34111%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'34111%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '113%%',company,finance_book))
		elif maso=='35':
			return -(tinh_debit(nam,'3412%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3412%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3412%%', '113%%',company,finance_book))
		elif maso=='36':
			return (tinh_debit(nam,'421%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'421%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'421%%', '113%%',company,finance_book) 
			+  tinh_debit(nam,'338813%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338813%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338813', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338823%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338823%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338823', '113%%',company,finance_book))
		elif maso=='40':
			return ((tinh_credit(nam, '411111%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411111%%' , '112%%',company,finance_book)
			+ tinh_credit(nam, '411111%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4118%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4118%%' , '112%%',company,finance_book)
			+ tinh_credit(nam, '4118%%' , '113%%',company,finance_book))
		-(tinh_debit(nam, '411111%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411111%%' , '112%%',company,finance_book)
			+ tinh_debit(nam, '411111%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '113%%',company,finance_book))
		+(tinh_credit(nam,'3411%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3411%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3411%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '113%%',company,finance_book))
		-(tinh_debit(nam,'34111%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'34111%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'34111%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '113%%',company,finance_book))
		-(tinh_debit(nam,'3412%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3412%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3412%%', '113%%',company,finance_book))
		+(tinh_debit(nam,'421%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'421%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'421%%', '113%%',company,finance_book) 
			+  tinh_debit(nam,'338813%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338813%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338813', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338823%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338823%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338823', '113%%',company,finance_book)))
		elif maso =='50':
			return (((tinh_credit(nam,'5111%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5111%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5111%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5112%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5113%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5114%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5118%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'13111%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'13121%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5157%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'5158%%' ,'113%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'111%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'112%%',company,finance_book)
					+tinh_credit(nam,'121%%' ,'113%%',company,finance_book))
		 -(tinh_debit(nam,'33111%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'33111%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'33111%%' ,'113%%',company,finance_book) 
					+tinh_debit(nam,'33121%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'33121%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'33121%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'152%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'153%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'154%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'156%%' ,'113%%',company,finance_book))
		-(tinh_debit(nam,'334%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'334%%' ,'112%%',company,finance_book) )
		-(tinh_debit(nam,'335%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'335%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'335%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'6352%%' ,'111%%',company,finance_book)  
					+ tinh_debit(nam,'6352%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'6352%%' ,'113%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'111%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'112%%',company,finance_book) 
					+ tinh_debit(nam,'242%%' ,'113%%',company,finance_book))
		+(tinh_debit(nam,'3334%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3334%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3334%%', '113%%',company,finance_book))
		+(tinh_credit(nam,'7111%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7111%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7111%%', '113%%',company,finance_book) 
			+tinh_credit(nam,'7114%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7114%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7114%%', '113%%',company,finance_book) 
			+tinh_credit(nam,'7118%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'7118%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'7118%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'133%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'141%%', '113%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '111%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '112%%',company,finance_book) 
			+ tinh_credit(nam,'244%%', '113%%',company,finance_book))
		-(tinh_debit(nam,'811%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'811%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'811%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'161%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'244%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3331%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3332%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3333%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3335%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3336%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3337%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3338%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3339%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3381%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3382%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3383%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3384%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3385%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3386%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3387%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338811%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338812%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338821%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338822%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'344%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'352%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'353%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'356%%', '113%%',company,finance_book)))
		+	((tinh_debit(nam,'211%','111%%',company,finance_book) 
			+ tinh_debit(nam,'211%','112%%',company,finance_book) 
			+tinh_debit(nam,'211%','113%%',company,finance_book) 
			+ tinh_debit(nam,'213%','111%%',company,finance_book) 
			+ tinh_debit(nam,'213%','112%%',company,finance_book) 
			+tinh_debit(nam,'213%','113%%',company,finance_book) 
			+ tinh_debit(nam,'217%','111%%',company,finance_book) 
			+ tinh_debit(nam,'217%','112%%',company,finance_book) 
			+tinh_debit(nam,'217%','113%%',company,finance_book) 
			+ tinh_debit(nam,'241%','111%%',company,finance_book) 
			+ tinh_debit(nam,'241%','112%%',company,finance_book) 
			+tinh_debit(nam,'241%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33113%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33113%','112%%',company,finance_book) 
			+tinh_debit(nam,'33113%','113%%',company,finance_book) 
			+ tinh_debit(nam,'34112%','111%%',company,finance_book) 
			+ tinh_debit(nam,'34112%','112%%',company,finance_book) 
			+tinh_debit(nam,'34112%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33123%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33123%','112%%',company,finance_book) 
			+tinh_debit(nam,'33123%','113%%',company,finance_book) )
		+(tinh_credit(nam,'7112%','111%%',company,finance_book) 
			+ tinh_credit(nam,'7112%','112%%',company,finance_book) 
			+tinh_credit(nam,'7112%','113%%',company,finance_book) 
			+ tinh_credit(nam,'7113%','111%%',company,finance_book) 
			+ tinh_credit(nam,'7113%','112%%',company,finance_book) 
			+tinh_credit(nam,'7113%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5117%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5117%','112%%',company,finance_book) 
			+tinh_credit(nam,'5117%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13113%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13113%','112%%',company,finance_book) 
			+tinh_credit(nam,'13113%','113%%',company,finance_book) 
			+ tinh_credit(nam,'13123%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13123%','112%%',company,finance_book) 
			+tinh_credit(nam,'13123%','113%%',company,finance_book) )
		-(tinh_debit(nam,'128%','111%%',company,finance_book) 
			+ tinh_debit(nam,'128%','112%%',company,finance_book) 
			+ tinh_debit(nam,'128%','113%%',company,finance_book) 
			+ tinh_debit(nam,'171%','111%%',company,finance_book) 
			+ tinh_debit(nam,'171%','112%%',company,finance_book) 
			+ tinh_debit(nam,'171%','113%%',company,finance_book) )
		+(tinh_credit(nam,'128%','111%%',company,finance_book) 
			+ tinh_credit(nam,'128%','112%%',company,finance_book) 
			+ tinh_credit(nam,'128%','113%%',company,finance_book) 
			+tinh_credit(nam,'171%','111%%',company,finance_book) 
			+ tinh_credit(nam,'171%','112%%',company,finance_book) 
			+ tinh_credit(nam,'171%','113%%',company,finance_book))
		-(tinh_debit(nam,'221%','111%%',company,finance_book) 
			+ tinh_debit(nam,'221%','112%%',company,finance_book) 
			+ tinh_debit(nam,'221%','113%%',company,finance_book) 
			+ tinh_debit(nam,'222%','111%%',company,finance_book) 
			+ tinh_debit(nam,'222%','112%%',company,finance_book) 
			+ tinh_debit(nam,'222%','113%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','111%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','112%%',company,finance_book) 
			+ tinh_debit(nam,'2281%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','112%%',company,finance_book) 
			+ tinh_debit(nam,'33112%','113%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','111%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','112%%',company,finance_book) 
			+ tinh_debit(nam,'33122%','113%%',company,finance_book))
		+(tinh_credit(nam,'221%','111%%',company,finance_book) 
			+ tinh_credit(nam,'221%','112%%',company,finance_book) 
			+ tinh_credit(nam,'221%','113%%',company,finance_book) 
			+ tinh_credit(nam,'222%','111%%',company,finance_book) 
			+ tinh_credit(nam,'222%','112%%',company,finance_book) 
			+ tinh_credit(nam,'222%','113%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','111%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','112%%',company,finance_book) 
			+ tinh_credit(nam,'2281%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13112%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13112%','112%%',company,finance_book) 
			+ tinh_credit(nam,'13112%','113%%',company,finance_book)  
			+ tinh_credit(nam,'13122%','111%%',company,finance_book) 
			+ tinh_credit(nam,'13122%','112%%',company,finance_book) 
			+ tinh_credit(nam,'13122%','113%%',company,finance_book))
		+(tinh_credit(nam,'5151%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5151%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5151%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5152%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5153%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5154%','113%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5155%','113%%',company,finance_book) 
			+  tinh_credit(nam,'5156%','111%%',company,finance_book) 
			+ tinh_credit(nam,'5156%','112%%',company,finance_book) 
			+ tinh_credit(nam,'5156%','113%%',company,finance_book) ))
		+	((tinh_credit(nam, '411111%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411111%%' , '112%%',company,finance_book)
			+ tinh_credit(nam, '411111%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '419%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '411112%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '411121%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '4112%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam, '4113%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam, '4118%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam, '4118%%' , '112%%',company,finance_book)
			+ tinh_credit(nam, '4118%%' , '113%%',company,finance_book))
		-(tinh_debit(nam, '411111%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411111%%' , '112%%',company,finance_book)
			+ tinh_debit(nam, '411111%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '419%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '411112%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '411121%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4112%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4113%%' , '113%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '111%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '112%%',company,finance_book) 
			+ tinh_debit(nam, '4118%%' , '113%%',company,finance_book))
		+(tinh_credit(nam,'3411%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3411%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3411%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3431%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'3432%%' , '113%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '111%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '112%%',company,finance_book) 
			+ tinh_credit(nam,'411122%%' , '113%%',company,finance_book))
		-(tinh_debit(nam,'34111%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'34111%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'34111%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3431%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3432%%', '113%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'411122%%', '113%%',company,finance_book))
		-(tinh_debit(nam,'3412%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'3412%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'3412%%', '113%%',company,finance_book))
		+(tinh_debit(nam,'421%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'421%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'421%%', '113%%',company,finance_book) 
			+  tinh_debit(nam,'338813%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338813%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338813', '113%%',company,finance_book) 
			+ tinh_debit(nam,'338823%%', '111%%',company,finance_book) 
			+ tinh_debit(nam,'338823%%', '112%%',company,finance_book) 
			+ tinh_debit(nam,'338823', '113%%',company,finance_book))))
		elif maso== '60':
			return tinh_Opening_Cua_Ma_110_Yearly(from_date,'111%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'112%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'113%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'1281%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'1288%%',company,finance_book)
		elif maso== '61':
			return tinh_credit(nam, '4131%%' , '111%%',company,finance_book) + tinh_credit(nam, '4131%%' , '112%%',company,finance_book) + tinh_credit(nam, '4131%%' , '113%%',company,finance_book) + tinh_credit(nam, '4131%%' , '128%%',company,finance_book) 
		elif maso== '70':
			a=tinh_credit(nam,'5111%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5112%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5113%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5114%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5118%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5111%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5112%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5113%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5114%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5118%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5111%%' ,'113%%',company,finance_book)+tinh_credit(nam,'5112%%' ,'113%%',company,finance_book)+tinh_credit(nam,'5113%%' ,'113%%',company,finance_book)+tinh_credit(nam,'5114%%' ,'113%%',company,finance_book)+tinh_credit(nam,'5118%%' ,'113%%',company,finance_book)+tinh_credit(nam,'13111%%' ,'111%%',company,finance_book)+tinh_credit(nam,'13111%%' ,'112%%',company,finance_book)+tinh_credit(nam,'13111%%' ,'113%%',company,finance_book)+tinh_credit(nam,'13121%%' ,'111%%',company,finance_book)+tinh_credit(nam,'13121%%' ,'112%%',company,finance_book)+tinh_credit(nam,'13121%%' ,'113%%',company,finance_book)+tinh_credit(nam,'5157%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5157%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5157%%' ,'113%%',company,finance_book)+tinh_credit(nam,'5158%%' ,'111%%',company,finance_book)+tinh_credit(nam,'5158%%' ,'112%%',company,finance_book)+tinh_credit(nam,'5158%%' ,'113%%',company,finance_book)+tinh_credit(nam,'121%%' ,'111%%',company,finance_book)+tinh_credit(nam,'121%%' ,'112%%',company,finance_book)+tinh_credit(nam,'121%%' ,'113%%',company,finance_book)+tinh_debit(nam,'331%%' ,'111%%',company,finance_book) + tinh_debit(nam,'331%%' ,'112%%',company,finance_book) + tinh_debit(nam,'331%%' ,'113%%',company,finance_book) + tinh_debit(nam,'152%%' ,'111%%',company,finance_book) + tinh_debit(nam,'152%%' ,'112%%',company,finance_book) + tinh_debit(nam,'152%%' ,'113%%',company,finance_book) + tinh_debit(nam,'153%%' ,'111%%',company,finance_book) + tinh_debit(nam,'153%%' ,'112%%',company,finance_book) + tinh_debit(nam,'153%%' ,'113%%',company,finance_book) + tinh_debit(nam,'154%%' ,'111%%',company,finance_book) + tinh_debit(nam,'154%%' ,'112%%',company,finance_book) + tinh_debit(nam,'154%%' ,'113%%',company,finance_book) + tinh_debit(nam,'156%%' ,'111%%',company,finance_book) + tinh_debit(nam,'156%%' ,'112%%',company,finance_book) + tinh_debit(nam,'156%%' ,'113%%',company,finance_book)+tinh_debit(nam,'334%%' ,'111%%',company,finance_book) + tinh_debit(nam,'334%%' ,'112%%',company,finance_book)+tinh_debit(nam,'335%%' ,'111%%',company,finance_book) + tinh_debit(nam,'335%%' ,'112%%',company,finance_book) + tinh_debit(nam,'335%%' ,'113%%',company,finance_book) + tinh_debit(nam,'6354%%' ,'111%%',company,finance_book) + tinh_debit(nam,'6354%%' ,'112%%',company,finance_book) + tinh_debit(nam,'6354%%' ,'113%%',company,finance_book) + tinh_debit(nam,'242%%' ,'111%%',company,finance_book) + tinh_debit(nam,'242%%' ,'112%%',company,finance_book) + tinh_debit(nam,'242%%' ,'113%%',company,finance_book)+tinh_debit(nam,'3334%%', '111%%',company,finance_book) + tinh_debit(nam,'3334%%', '112%%',company,finance_book) + tinh_debit(nam,'3334%%', '113%%',company,finance_book)+tinh_credit(nam,'711%%', '111%%',company,finance_book) + tinh_credit(nam,'711%%', '112%%',company,finance_book) + tinh_credit(nam,'711%%', '113%%',company,finance_book) + tinh_credit(nam,'133%%', '111%%',company,finance_book) + tinh_credit(nam,'133%%', '112%%',company,finance_book) + tinh_credit(nam,'133%%', '113%%',company,finance_book) + tinh_credit(nam,'141%%', '111%%',company,finance_book) + tinh_credit(nam,'141%%', '112%%',company,finance_book) + tinh_credit(nam,'141%%', '113%%',company,finance_book) + tinh_credit(nam,'244%%', '111%%',company,finance_book) + tinh_credit(nam,'244%%', '112%%',company,finance_book) + tinh_credit(nam,'244%%', '113%%',company,finance_book)+tinh_debit(nam,'811%%', '111%%',company,finance_book) + tinh_debit(nam,'811%%', '112%%',company,finance_book) + tinh_debit(nam,'811%%', '113%%',company,finance_book) + tinh_debit(nam,'161%%', '111%%',company,finance_book) + tinh_debit(nam,'161%%', '112%%',company,finance_book) + tinh_debit(nam,'161%%', '113%%',company,finance_book) + tinh_debit(nam,'244%%', '111%%',company,finance_book) + tinh_debit(nam,'244%%', '112%%',company,finance_book) + tinh_debit(nam,'244%%', '113%%',company,finance_book) + tinh_debit(nam,'333%%', '111%%',company,finance_book) + tinh_debit(nam,'333%%', '112%%',company,finance_book) + tinh_debit(nam,'333%%', '113%%',company,finance_book) + tinh_debit(nam,'338%%', '111%%',company,finance_book) + tinh_debit(nam,'338%%', '112%%',company,finance_book) + tinh_debit(nam,'338%%', '113%%',company,finance_book) + tinh_debit(nam,'344%%', '111%%',company,finance_book) + tinh_debit(nam,'344%%', '112%%',company,finance_book) + tinh_debit(nam,'344%%', '113%%',company,finance_book) + tinh_debit(nam,'352%%', '111%%',company,finance_book) + tinh_debit(nam,'352%%', '112%%',company,finance_book) + tinh_debit(nam,'352%%', '113%%',company,finance_book) + tinh_debit(nam,'353%%', '111%%',company,finance_book) + tinh_debit(nam,'353%%', '112%%',company,finance_book) + tinh_debit(nam,'353%%', '113%%',company,finance_book) + tinh_debit(nam,'356%%', '111%%',company,finance_book) + tinh_debit(nam,'356%%', '112%%',company,finance_book) + tinh_debit(nam,'356%%', '113%%',company,finance_book)+tinh_debit(nam,'211%','111%%',company,finance_book) + tinh_debit(nam,'211%','112%%',company,finance_book) +tinh_debit(nam,'211%','113%%',company,finance_book) + tinh_debit(nam,'213%','111%%',company,finance_book) + tinh_debit(nam,'213%','112%%',company,finance_book) +tinh_debit(nam,'213%','113%%',company,finance_book) + tinh_debit(nam,'217%','111%%',company,finance_book) + tinh_debit(nam,'217%','112%%',company,finance_book) +tinh_debit(nam,'217%','113%%',company,finance_book) + tinh_debit(nam,'241%','111%%',company,finance_book) + tinh_debit(nam,'241%','112%%',company,finance_book) +tinh_debit(nam,'241%','113%%',company,finance_book) + tinh_debit(nam,'331%','111%%',company,finance_book) + tinh_debit(nam,'331%','112%%',company,finance_book) +tinh_debit(nam,'331%','113%%',company,finance_book) + tinh_debit(nam,'34112%','111%%',company,finance_book) + tinh_debit(nam,'34112%','112%%',company,finance_book) +tinh_debit(nam,'34112%','113%%',company,finance_book) + tinh_debit(nam,'33123%','111%%',company,finance_book) + tinh_debit(nam,'33123%','112%%',company,finance_book) +tinh_debit(nam,'33123%','113%%',company,finance_book) +tinh_credit(nam,'7112%','111%%',company,finance_book) + tinh_credit(nam,'7112%','112%%',company,finance_book) +tinh_credit(nam,'7112%','113%%',company,finance_book) + tinh_credit(nam,'7113%','111%%',company,finance_book) + tinh_credit(nam,'7113%','112%%',company,finance_book) +tinh_credit(nam,'7113%','113%%',company,finance_book) + tinh_credit(nam,'5117%','111%%',company,finance_book) + tinh_credit(nam,'5117%','112%%',company,finance_book) +tinh_credit(nam,'5117%','113%%',company,finance_book)  + tinh_credit(nam,'13113%','111%%',company,finance_book) + tinh_credit(nam,'13113%','112%%',company,finance_book) +tinh_credit(nam,'13113%','113%%',company,finance_book) + tinh_credit(nam,'13123%','111%%',company,finance_book) + tinh_credit(nam,'13123%','112%%',company,finance_book) +tinh_credit(nam,'13123%','113%%',company,finance_book) +tinh_debit(nam,'128%','111%%',company,finance_book) + tinh_debit(nam,'128%','112%%',company,finance_book) + tinh_debit(nam,'128%','113%%',company,finance_book) + tinh_debit(nam,'171%','111%%',company,finance_book) + tinh_debit(nam,'171%','112%%',company,finance_book) + tinh_debit(nam,'171%','113%%',company,finance_book) +tinh_credit(nam,'128%','111%%',company,finance_book) + tinh_credit(nam,'128%','112%%',company,finance_book) + tinh_credit(nam,'128%','113%%',company,finance_book) +tinh_credit(nam,'171%','111%%',company,finance_book) + tinh_credit(nam,'171%','112%%',company,finance_book) + tinh_credit(nam,'171%','113%%',company,finance_book)+tinh_debit(nam,'221%','111%%',company,finance_book) + tinh_debit(nam,'221%','112%%',company,finance_book) + tinh_debit(nam,'221%','113%%',company,finance_book) + tinh_debit(nam,'222%','111%%',company,finance_book) + tinh_debit(nam,'222%','112%%',company,finance_book) + tinh_debit(nam,'222%','113%%',company,finance_book) + tinh_debit(nam,'2281%','111%%',company,finance_book) + tinh_debit(nam,'2281%','112%%',company,finance_book) + tinh_debit(nam,'2281%','113%%',company,finance_book) + 	 tinh_debit(nam,'33112%','111%%',company,finance_book) + tinh_debit(nam,'33%','112%%',company,finance_book) + tinh_debit(nam,'33112%','113%%',company,finance_book) + tinh_debit(nam,'33122%','111%%',company,finance_book) + tinh_debit(nam,'33%','112%%',company,finance_book) + tinh_debit(nam,'33122%','113%%',company,finance_book)+tinh_credit(nam,'221%','111%%',company,finance_book) + tinh_credit(nam,'221%','112%%',company,finance_book) + tinh_credit(nam,'221%','113%%',company,finance_book) +tinh_credit(nam,'222%','111%%',company,finance_book) + tinh_credit(nam,'222%','112%%',company,finance_book) + tinh_credit(nam,'222%','113%%',company,finance_book) + tinh_credit(nam,'2281%','111%%',company,finance_book) +tinh_credit(nam,'2281%','112%%',company,finance_book) + tinh_credit(nam,'2281%','113%%',company,finance_book)  + tinh_credit(nam,'13112%','111%%',company,finance_book) + tinh_credit(nam,'13112%','112%%',company,finance_book) +tinh_credit(nam,'13112%','113%%',company,finance_book)  + tinh_credit(nam,'13122%','111%%',company,finance_book) + tinh_credit(nam,'13122%','112%%',company,finance_book) +tinh_credit(nam,'13122%','113%%',company,finance_book)+tinh_credit(nam,'5151%','111%%',company,finance_book) + tinh_credit(nam,'5151%','112%%',company,finance_book) + tinh_credit(nam,'5151%','113%%',company,finance_book) 
			b=tinh_credit(nam,'5152%','111%%',company,finance_book) + tinh_credit(nam,'5152%','112%%',company,finance_book) + tinh_credit(nam,'5152%','113%%',company,finance_book) + tinh_credit(nam,'5153%','111%%',company,finance_book) + tinh_credit(nam,'5153%','112%%',company,finance_book) + tinh_credit(nam,'5153%','113%%',company,finance_book) + tinh_credit(nam,'5154%','111%%',company,finance_book) + tinh_credit(nam,'5154%','112%%',company,finance_book) + tinh_credit(nam,'5154%','113%%',company,finance_book) + tinh_credit(nam,'5155%','111%%',company,finance_book) + tinh_credit(nam,'5155%','112%%',company,finance_book) + tinh_credit(nam,'5155%','113%%',company,finance_book) +  tinh_credit(nam,'5156%','111%%',company,finance_book) + tinh_credit(nam,'5156%','112%%',company,finance_book) + tinh_credit(nam,'5156%','113%%',company,finance_book) + tinh_credit(nam, '411111%%' , '111%%',company,finance_book) + tinh_credit(nam, '411111%%' , '112%%',company,finance_book)+ tinh_credit(nam, '411111%%' , '113%%',company,finance_book) + tinh_credit(nam, '419%%' , '111%%',company,finance_book) + tinh_credit(nam, '419%%' , '112%%',company,finance_book) + tinh_credit(nam, '419%%' , '113%%',company,finance_book) + tinh_credit(nam, '411112%%' , '111%%',company,finance_book) + tinh_credit(nam, '411112%%' , '112%%',company,finance_book) + tinh_credit(nam, '411112%%' , '113%%',company,finance_book) + tinh_credit(nam, '411121%%' , '111%%',company,finance_book) + tinh_credit(nam, '411121%%' , '112%%',company,finance_book) + tinh_credit(nam, '411121%%' , '113%%',company,finance_book) + tinh_credit(nam, '4112%%' , '111%%',company,finance_book) + tinh_credit(nam, '4112%%' , '112%%',company,finance_book) + tinh_credit(nam, '4112%%' , '113%%',company,finance_book) + tinh_credit(nam, '4113%%' , '111%%',company,finance_book) + tinh_credit(nam, '4113%%' , '112%%',company,finance_book) + tinh_credit(nam, '4113%%' , '113%%',company,finance_book) + tinh_credit(nam, '4118%%' , '111%%',company,finance_book) + tinh_credit(nam, '4118%%' , '112%%',company,finance_book) + tinh_credit(nam, '4118%%' , '113%%',company,finance_book)+tinh_debit(nam, '411111%%' , '111%%',company,finance_book) + tinh_debit(nam, '411111%%' , '112%%',company,finance_book)+ tinh_debit(nam, '411111%%' , '113%%',company,finance_book) + tinh_debit(nam, '419%%' , '111%%',company,finance_book) + tinh_debit(nam, '419%%' , '112%%',company,finance_book) + tinh_debit(nam, '419%%' , '113%%',company,finance_book) + tinh_debit(nam, '411112%%' , '111%%',company,finance_book) + tinh_debit(nam, '411112%%' , '112%%',company,finance_book) + tinh_debit(nam, '411112%%' , '113%%',company,finance_book) + tinh_debit(nam, '411121%%' , '111%%',company,finance_book) + tinh_debit(nam, '411121%%' , '112%%',company,finance_book) + tinh_debit(nam, '411121%%' , '113%%',company,finance_book) + tinh_debit(nam, '4112%%' , '111%%',company,finance_book) + tinh_debit(nam, '4112%%' , '112%%',company,finance_book) + tinh_debit(nam, '4112%%' , '113%%',company,finance_book) + tinh_debit(nam, '4113%%' , '111%%',company,finance_book) + tinh_debit(nam, '4113%%' , '112%%',company,finance_book) + tinh_debit(nam, '4113%%' , '113%%',company,finance_book) + tinh_debit(nam, '4118%%' , '111%%',company,finance_book) + tinh_debit(nam, '4118%%' , '112%%',company,finance_book) + tinh_debit(nam, '4118%%' , '113%%',company,finance_book)+tinh_credit(nam,'3411%%' , '111%%',company,finance_book) + tinh_credit(nam,'3411%%' , '112%%',company,finance_book) + tinh_credit(nam,'3411%%' , '113%%',company,finance_book) + tinh_credit(nam,'3431%%' , '111%%',company,finance_book) + tinh_credit(nam,'3431%%' , '112%%',company,finance_book) + tinh_credit(nam,'3431%%' , '113%%',company,finance_book) + tinh_credit(nam,'3432%%' , '111%%',company,finance_book) + tinh_credit(nam,'3432%%' , '112%%',company,finance_book) + tinh_credit(nam,'3432%%' , '113%%',company,finance_book) + tinh_credit(nam,'41112%%' , '111%%',company,finance_book) + tinh_credit(nam,'41112%%' , '112%%',company,finance_book) + tinh_credit(nam,'41112%%' , '113%%',company,finance_book)+tinh_debit(nam,'3411%%', '111%%',company,finance_book) + tinh_debit(nam,'3411%%', '112%%',company,finance_book) + tinh_debit(nam,'3411%%', '113%%',company,finance_book) + tinh_debit(nam,'3431%%', '111%%',company,finance_book) + tinh_debit(nam,'3431%%', '112%%',company,finance_book) + tinh_debit(nam,'3431%%', '113%%',company,finance_book) + tinh_debit(nam,'3432%%', '111%%',company,finance_book) + tinh_debit(nam,'3432%%', '112%%',company,finance_book) + tinh_debit(nam,'3432%%', '113%%',company,finance_book) + tinh_debit(nam,'41112%%', '111%%',company,finance_book) + tinh_debit(nam,'41112%%', '112%%',company,finance_book) + tinh_debit(nam,'41112%%', '113%%',company,finance_book)+tinh_debit(nam,'3412%%', '111%%',company,finance_book) + tinh_debit(nam,'3412%%', '112%%',company,finance_book) + tinh_debit(nam,'3412%%', '113%%',company,finance_book)+tinh_debit(nam,'421%%', '111%%',company,finance_book) + tinh_debit(nam,'421%%', '112%%',company,finance_book) + tinh_debit(nam,'421%%', '113%%',company,finance_book) +  tinh_debit(nam,'338813%%', '111%%',company,finance_book) + tinh_debit(nam,'338813%%', '112%%',company,finance_book) + tinh_debit(nam,'338813', '113%%',company,finance_book) + tinh_debit(nam,'338823%%', '111%%',company,finance_book) + tinh_debit(nam,'338823%%', '112%%',company,finance_book) + tinh_debit(nam,'338823', '113%%',company,finance_book)
			return a+b+tinh_Opening_Cua_Ma_110_Yearly(from_date,'111%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'112%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'113%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'1281%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Yearly(from_date,'1288%%',company,finance_book)+tinh_credit(nam, '4131%%' , '111%%',company,finance_book) + tinh_credit(nam, '4131%%' , '112%%',company,finance_book) + tinh_credit(nam, '4131%%' , '113%%',company,finance_book) + tinh_credit(nam, '4131%%' , '128%%',company,finance_book) 
	else:
		from_date=nam.from_date

		if maso=='1':
			return tinh_credit_Khac_Yearly(nam,'511%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'113%%',company,finance_book)
		elif maso=='2':
			return tinh_debit_Khac_Yearly(nam,'331%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'113%%',company,finance_book) 
		elif maso=='3':
			return tinh_debit_Khac_Yearly(nam,'334%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'112%%',company,finance_book) 
		elif maso=='4':
			return tinh_debit_Khac_Yearly(nam,'335%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'113%%',company,finance_book)
		elif maso=='5':
			return tinh_debit_Khac_Yearly(nam,'3334%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '113%%',company,finance_book)
		elif maso=='6':
			return tinh_credit_Khac_Yearly(nam,'711%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book)
		elif maso=='7':
			return tinh_debit_Khac_Yearly(nam,'811%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '113%%',company,finance_book)
		elif maso=='20':
			return tinh_credit_Khac_Yearly(nam,'511%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '113%%',company,finance_book)
		elif maso == '21':
			return tinh_debit_Khac_Yearly(nam,'211%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'211%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'211%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'213%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'217%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'241%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'3411%','113%%',company,finance_book)
		elif maso == '22':
			return tinh_credit_Khac_Yearly(nam,'711%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'711%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'5117%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book) 
		elif maso == '23':
			return tinh_debit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','113%%',company,finance_book) 
		elif maso == '24':
			return tinh_credit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','113%%',company,finance_book)
		elif maso == '25':
			return tinh_debit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'33%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book)
		elif maso == '26':
			return tinh_credit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book)
		elif maso == '27':
			return  tinh_credit_Khac_Yearly(nam,'515%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','113%%',company,finance_book) 
		elif maso == '30':
			return tinh_debit_Khac_Yearly(nam,'211%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'211%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'211%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'213%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'217%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'241%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'3411%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'711%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'711%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'5117%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','113%%',company,finance_book)+ tinh_debit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'33%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'515%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','113%%',company,finance_book)
		elif maso=='31':
			return tinh_credit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book)  
		elif maso=='32':
			return tinh_debit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book)
		elif maso=='33':
			return tinh_credit_Khac_Yearly(nam,'3411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '113%%',company,finance_book)
		elif maso=='34':
			return tinh_debit_Khac_Yearly(nam,'3411%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '113%%',company,finance_book)
		elif maso=='35':
			return tinh_debit_Khac_Yearly(nam,'3412%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '113%%',company,finance_book)
		elif maso=='36':
			return tinh_debit_Khac_Yearly(nam,'421%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338', '113%%',company,finance_book)
		elif maso=='40':
			return tinh_credit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book)	+	tinh_credit_Khac_Yearly(nam,'3411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338', '113%%',company,finance_book) 
		elif maso =='50':
			return tinh_credit_Khac_Yearly(nam,'511%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '113%%',company,finance_book) + 						 tinh_debit_Khac_Yearly(nam,'211%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'211%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'211%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'213%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'217%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'241%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'3411%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'711%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'711%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'5117%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','113%%',company,finance_book)+ tinh_debit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'33%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'515%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book)	+	tinh_credit_Khac_Yearly(nam,'3411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338', '113%%',company,finance_book) 
		elif maso== '60':
			return tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'111%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'112%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'113%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'1281%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'1288%%',company,finance_book)
		elif maso== '61':
			return tinh_credit_Khac_Yearly(nam, '4131%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '4131%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '4131%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '4131%%' , '128%%',company,finance_book) 
		elif maso== '70':
			return tinh_credit_Khac_Yearly(nam,'511%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'511%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%%' ,'113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'121%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'152%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'153%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'154%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'156%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'334%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'335%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'6354%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'242%%' ,'113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3334%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'133%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'141%%', '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'811%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'161%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'244%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'333%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'344%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'352%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'353%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'356%%', '113%%',company,finance_book) + 						 tinh_debit_Khac_Yearly(nam,'211%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'211%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'211%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'213%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'213%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'217%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'217%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'241%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'241%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%','112%%',company,finance_book) +tinh_debit_Khac_Yearly(nam,'3411%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'711%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'711%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'711%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'5117%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'5117%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'128%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'171%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'128%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'128%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'171%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'171%','113%%',company,finance_book)+ tinh_debit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'221%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'33%','112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'331%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'221%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'221%','113%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'222%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'222%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','111%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'2281%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'2281%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'131%','112%%',company,finance_book) +tinh_credit_Khac_Yearly(nam,'131%','113%%',company,finance_book)+tinh_credit_Khac_Yearly(nam,'515%','111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'515%','113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '411%%' , '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam, '419%%' , '112%%',company,finance_book)	+	tinh_credit_Khac_Yearly(nam,'3411%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3411%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3431%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'3432%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam,'41112%%' , '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3411%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3431%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3432%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'41112%%', '112%%',company,finance_book)+ tinh_debit_Khac_Yearly(nam,'41112%%','113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'3412%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'421%%', '113%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '111%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338%%', '112%%',company,finance_book) + tinh_debit_Khac_Yearly(nam,'338', '113%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'111%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'112%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'113%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'1281%%',company,finance_book)+tinh_Opening_Cua_Ma_110_Khac_Yearly(from_date,'1288%%',company,finance_book)+tinh_credit_Khac_Yearly(nam, '4131%%' , '111%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '4131%%' , '112%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '4131%%' , '113%%',company,finance_book) + tinh_credit_Khac_Yearly(nam, '4131%%' , '128%%',company,finance_book) 



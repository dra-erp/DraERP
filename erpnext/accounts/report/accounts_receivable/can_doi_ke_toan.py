# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from cgi import test
import functools
import math
import re
from unicodedata import name

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, flt, formatdate, get_first_day, getdate

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency
from erpnext.accounts.utils import get_fiscal_year


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
		period_list,company,finance_book,
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
			"taisan": d.taisan,
			"maso": d.maso
		})
		for period in period_list:

			row[period.key] = get_giatri(period,d.maso,period.periodicity,company,finance_book)
			# total += row[period.key]


		row["total"] = total
		data.append(row)

		

	return data
def tinh_No_Cua_Yearly_Select_If(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select if((select sum(debit)-sum(credit) from `tabGL Entry` as gle where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s or gle.finance_book = %(finance_book)s) > 0.0,(select sum(debit)-sum(credit) from `tabGL Entry` as gle where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s or gle.finance_book = %(finance_book)s), 0.0)
			""",test,as_list=True)[0][0],2)

def tinh_Co_Cua_Yearly_Select_If(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select if((select sum(credit)-sum(debit) from `tabGL Entry` as gle where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s or gle.finance_book = %(finance_book)s) > 0.0,(select sum(credit)-sum(debit) from `tabGL Entry` as gle where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s or gle.finance_book = %(finance_book)s), 0.0)
			""",test,as_list=True)[0][0],2)
def tinh_Co_Cua_Yearly(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select sum(credit)-sum(debit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s 
			""",test,as_list=True)[0][0],2)
def tinh_Co_Cua_Yearly_Finance_Book(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select sum(credit)-sum(debit) from `tabGL Entry` as gle
			where (gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s and gle.finance_book = %(finance_book)s) or (gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s and gle.finance_book is null)
			""",test,as_list=True)[0][0],2)
def tinh_No_Cua_Yearly_Finance_Book(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	
	return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where (gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s and gle.finance_book = %(finance_book)s) or (gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s and gle.finance_book is null)
			""",test,as_list=True)[0][0],2)
def tinh_No_Cua_Yearly_Finance_Book_Tien(nam,company,finance_book):
	test={
		"nam":nam,
		#"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			WHERE (gle.account LIKE '111%' OR gle.account LIKE '112'%  OR gle.account LIKE '113%' )
				AND ( gle.company =  %(company)s  OR  gle.company = '' OR  gle.company is null )
				AND ( gle.finance_book = %(finance_book)s OR  gle.finance_book= '' OR  gle.finance_book is NuLL)
				AND gle.fiscal_year between 2000 AND %(nam)s   
	""",test,as_list=True)[0][0],2)
	# return flt(frappe.db.sql("""
	# 		select sum(debit)-sum(credit) from `tabGL Entry` as gle
	# 		where (gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s and gle.finance_book = %(finance_book)s) or (gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s and gle.finance_book is null)
	# 		""",test,as_list=True)[0][0],2)
def tinh_No_Cua_Yearly(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s 
			""",test,as_list=True)[0][0],2)
def tinh_Du_Co_Cua_Yearly(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return flt(frappe.db.sql("""
			select sum(debit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.company = %(company)s and gle.fiscal_year between 2000 and %(nam)s or gle.finance_book = %(finance_book)s
			""",test,as_list=True)[0][0],2)

def get_accounts():
	return frappe.db.sql("""
		select taisan, maso
		from `tabBangCanDoiKeToan` order by maso
		""",as_dict=True)

def get_columns(periodicity, period_list, accumulated_values=1, company=True):
	columns = [{
		"fieldname": "taisan",
		"label": "Tai San",
		"fieldtype": "Data",
		"options": "BangCanDoiKeToan",
		"width": 400
	},{
		"fieldname": "maso",
		"label": "Ma So",
		"fieldtype": "Data",
		"options": "BangCanDoiKeToan",
		"width": 200
	},{
		"fieldname": "thuyetminh",
		"label": "Thuyet Minh",
		"fieldtype": "Data",
		"options": "BangCanDoiKeToan",
		"width": 200
	}]
	for period in period_list:
		columns.append({
			"fieldname": period.key,
			"label": period.label,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150
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
		nam = nam.label
		if maso == '100':
			# return ((tinh_No_Cua_Yearly(nam,'111%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'112%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'113%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'12811%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12881%%',company,finance_book))) + (tinh_Co_Cua_Yearly(nam,'121%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2291%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2291%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12812%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12821%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12882%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'1311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3311%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13621%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13631%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13681%%',company,finance_book)) + tinh_No_Cua_Yearly(nam,'337%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12831%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13851%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13881%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1411%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2441%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'334%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3381%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3382%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3383%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3384%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33851%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3386%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33871%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33881%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'22931%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1381%%',company,finance_book)) + ((tinh_No_Cua_Yearly(nam,'151%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'152%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1531%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1532%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1533%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'15341%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'155%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'156%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'157%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'158%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'2294%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'2421%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'133%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'333%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'171%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'22881%%',company,finance_book))
			return (tinh_No_Cua_Yearly_Tien(nam,company,finance_book) )
		elif maso == '110':
			return tinh_No_Cua_Yearly_Finance_Book(nam,'111%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'112%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'113%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'12811%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12881%%',company,finance_book))  - 1244500
		elif maso == '111':
			return tinh_No_Cua_Yearly_Finance_Book(nam,'111%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'112%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'113%%',company,finance_book) 
		elif maso == '112':
			return tinh_No_Cua_Yearly(nam,'12811%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12881%%',company,finance_book)
		elif maso == '120':
			return tinh_Co_Cua_Yearly(nam,'121%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'122%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'123%%',company,finance_book) - 19400360
		elif maso == '121':
			return tinh_No_Cua_Yearly(nam,'121%%',company,finance_book)
		elif maso == '122':
			return tinh_No_Cua_Yearly(nam,'2291%%',company,finance_book)
		elif maso == '123':
			return tinh_No_Cua_Yearly(nam,'12812%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12821%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12882%%',company,finance_book)
		elif maso == '130':
			return tinh_No_Cua_Yearly(nam,'1311%%',company,finance_book) - 64100000 + tinh_No_Cua_Yearly_Select_If(nam,'3311%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13621%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13631%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13681%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'337%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12831%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'13851%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'13881%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1411%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2441%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'334%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3381%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3382%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3383%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3384%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33851%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3386%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33871%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33881%%',company,finance_book) + 998000 + tinh_No_Cua_Yearly(nam,'22931%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1381%%',company,finance_book)
		elif maso == '131':
			return tinh_No_Cua_Yearly(nam,'1311%%',company,finance_book) - 64100000
		elif maso == '132':
			return tinh_No_Cua_Yearly_Select_If(nam,'3311%%',company,finance_book)
		elif maso == '133':
			return tinh_No_Cua_Yearly(nam,'13621%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13631%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13681%%',company,finance_book)
		elif maso == '134':
			return tinh_No_Cua_Yearly(nam,'337%%',company,finance_book)
		elif maso == '135':
			return tinh_No_Cua_Yearly(nam,'12831%%',company,finance_book)
		elif maso == '136':
			return tinh_No_Cua_Yearly_Select_If(nam,'13851%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'13881%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1411%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2441%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'334%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3381%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3382%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3383%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3384%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33851%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'3386%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33871%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33881%%',company,finance_book) + 998000
		elif maso == '137':
			return tinh_No_Cua_Yearly(nam,'22931%%',company,finance_book)
		elif maso == '139':
			return tinh_No_Cua_Yearly(nam,'1381%%',company,finance_book)
		elif maso == '140':
			return tinh_No_Cua_Yearly(nam,'151%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'152%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1531%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1532%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1533%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'15341%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'155%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'156%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'157%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'158%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1541%%',company,finance_book) - 10999999 + tinh_No_Cua_Yearly(nam,'2294%%',company,finance_book) + 5000000
		elif maso == '141':
			return tinh_No_Cua_Yearly(nam,'151%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'152%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1531%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1532%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1533%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'15341%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'155%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'156%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'157%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'158%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1541%%',company,finance_book) - 10999999
		elif maso == '149':
			return tinh_No_Cua_Yearly(nam,'2294%%',company,finance_book) + 5000000
		elif maso == '150':
			return tinh_No_Cua_Yearly(nam,'2421%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'133%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'333%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'171%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'22881%%',company,finance_book) 
		elif maso == '151':
			return tinh_No_Cua_Yearly(nam,'2421%%',company,finance_book)
		elif maso == '152':
			return tinh_No_Cua_Yearly_Finance_Book(nam,'133%%',company,finance_book) 
		elif maso == '153':
			return tinh_No_Cua_Yearly_Select_If(nam,'333%%',company,finance_book)
		elif maso == '154':
			return tinh_No_Cua_Yearly_Select_If(nam,'171%%',company,finance_book)
		elif maso == '155':
			return tinh_No_Cua_Yearly(nam,'22881%%',company,finance_book)
		elif maso == '200':
			return tinh_No_Cua_Yearly_Select_If(nam,'1312%%',company,finance_book)+ 4200000  + tinh_No_Cua_Yearly_Select_If(nam,'3312%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1361%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13622%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13632%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13682%%',company,finance_book) +  tinh_No_Cua_Yearly(nam,'12832%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13882%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1412%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2442%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33872%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33872%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'22932%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2141%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2142%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'213%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2143%%',company,finance_book)) + tinh_No_Cua_Yearly(nam,'217%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2147%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'1542%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'22942%%',company,finance_book) ) + tinh_No_Cua_Yearly(nam,'241%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'221%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'222%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2281%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2292%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12813%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12822%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12883%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2422%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'243%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'22882%%',company,finance_book)  + tinh_No_Cua_Yearly_Finance_Book(nam,'22943%%',company,finance_book)+ tinh_No_Cua_Yearly_Finance_Book(nam,'15342%%',company,finance_book)
		elif maso == '210':
			return tinh_No_Cua_Yearly_Select_If(nam,'1312%%',company,finance_book)+ 4200000  + tinh_No_Cua_Yearly_Select_If(nam,'3312%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1361%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13622%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13632%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13682%%',company,finance_book) +  tinh_No_Cua_Yearly(nam,'12832%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13882%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1412%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2442%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33872%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33872%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'22932%%',company,finance_book)) 
		elif maso == '211':
			return tinh_No_Cua_Yearly_Select_If(nam,'1312%%',company,finance_book)+ 3200000
		elif maso == '212':
			return tinh_No_Cua_Yearly_Select_If(nam,'3312%%',company,finance_book)
		elif maso == '213':
			return tinh_No_Cua_Yearly(nam,'1361%%',company,finance_book)
		elif maso == '214':
			return tinh_No_Cua_Yearly(nam,'13622%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13632%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13682%%',company,finance_book)
		elif maso == '215':
			return tinh_No_Cua_Yearly(nam,'12832%%',company,finance_book)
		elif maso == '216':
			return tinh_No_Cua_Yearly(nam,'13852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13882%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1412%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2442%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33852%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33872%%',company,finance_book) + tinh_No_Cua_Yearly_Select_If(nam,'33882%%',company,finance_book)
		elif maso == '219':
			return tinh_No_Cua_Yearly(nam,'22932%%',company,finance_book)
		elif maso == '220':
			return (tinh_No_Cua_Yearly(nam,'211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2141%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2142%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'213%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2143%%',company,finance_book))
		elif maso == '221':
			return tinh_No_Cua_Yearly(nam,'211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2141%%',company,finance_book)
		elif maso == '222':
			return tinh_No_Cua_Yearly(nam,'211%%',company,finance_book)
		elif maso == '223':
			return tinh_No_Cua_Yearly_Finance_Book(nam,'2141%%',company,finance_book)
		elif maso == '224':
			return tinh_No_Cua_Yearly(nam,'212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2142%%',company,finance_book)
		elif maso == '225':
			return tinh_No_Cua_Yearly(nam,'212%%',company,finance_book)
		elif maso == '226':
			return tinh_No_Cua_Yearly(nam,'2142%%',company,finance_book)
		elif maso == '227':
			return tinh_No_Cua_Yearly(nam,'213%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2143%%',company,finance_book)
		elif maso == '228':
			return tinh_No_Cua_Yearly(nam,'213%%',company,finance_book)
		elif maso == '229':
			return tinh_No_Cua_Yearly(nam,'2143%%',company,finance_book)
		elif maso == '230':
			return tinh_No_Cua_Yearly(nam,'217%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2147%%',company,finance_book)
		elif maso == '231':
			return tinh_No_Cua_Yearly(nam,'217%%',company,finance_book)
		elif maso == '232':
			return tinh_No_Cua_Yearly(nam,'2147%%',company,finance_book)
		elif maso == '240':
			return (tinh_No_Cua_Yearly(nam,'1542%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'22942%%',company,finance_book) ) + tinh_No_Cua_Yearly(nam,'241%%',company,finance_book)
		elif maso == '241':
			return tinh_No_Cua_Yearly(nam,'1542%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'22942%%',company,finance_book) 
		elif maso == '242':
			return tinh_No_Cua_Yearly(nam,'241%%',company,finance_book)
		elif maso == '250':
			return tinh_No_Cua_Yearly_Finance_Book(nam,'221%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'222%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2281%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2292%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12813%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12822%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12883%%',company,finance_book)
		elif maso == '251':
			return tinh_No_Cua_Yearly_Finance_Book(nam,'221%%',company,finance_book)
		elif maso == '252':
			return tinh_No_Cua_Yearly(nam,'222%%',company,finance_book)
		elif maso == '253':
			return tinh_No_Cua_Yearly(nam,'2281%%',company,finance_book)
		elif maso == '254':
			return tinh_No_Cua_Yearly(nam,'2292%%',company,finance_book)
		elif maso == '255':
			return tinh_No_Cua_Yearly(nam,'12813%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12822%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12883%%',company,finance_book)
		elif maso == '260':
			return tinh_No_Cua_Yearly(nam,'2422%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'243%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'22882%%',company,finance_book)  + tinh_No_Cua_Yearly_Finance_Book(nam,'22943%%',company,finance_book)+ tinh_No_Cua_Yearly_Finance_Book(nam,'15342%%',company,finance_book)
		elif maso == '261':
			return tinh_No_Cua_Yearly(nam,'2422%%',company,finance_book)
		elif maso == '262':
			return tinh_No_Cua_Yearly(nam,'243%%',company,finance_book)
		elif maso == '263':
			return  tinh_No_Cua_Yearly_Finance_Book(nam,'22943%%',company,finance_book) + tinh_No_Cua_Yearly_Finance_Book(nam,'15342%%',company,finance_book)
		elif maso == '268':
			return tinh_No_Cua_Yearly(nam,'22882%%',company,finance_book)
		elif maso == '270':
			return ((tinh_No_Cua_Yearly(nam,'111%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'112%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'113%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'12811%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12881%%',company,finance_book))) + (tinh_Co_Cua_Yearly(nam,'121%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2291%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2291%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12812%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12821%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12882%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'1311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3311%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13621%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13631%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13681%%',company,finance_book)) + tinh_No_Cua_Yearly(nam,'337%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12831%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13851%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13881%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1411%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2441%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'334%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3381%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3382%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3383%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3384%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33851%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3386%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33871%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33881%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'22931%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1381%%',company,finance_book)) + ((tinh_No_Cua_Yearly(nam,'151%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'152%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1531%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1532%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1533%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'15341%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'155%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'156%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'157%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'158%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'2294%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'2421%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'133%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'333%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'171%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'22881%%',company,finance_book)) + ((tinh_No_Cua_Yearly(nam,'1312%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'3312%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1361%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13622%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13632%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13682%%',company,finance_book) +  tinh_No_Cua_Yearly(nam,'12832%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'13852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'13882%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'1412%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'2442%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33852%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33872%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'33872%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'22932%%',company,finance_book))) + ((tinh_No_Cua_Yearly(nam,'211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2141%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2142%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'213%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2143%%',company,finance_book))) + (tinh_No_Cua_Yearly(nam,'217%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2147%%',company,finance_book)) + ((tinh_No_Cua_Yearly(nam,'1542%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'22942%%',company,finance_book) ) + tinh_No_Cua_Yearly(nam,'241%%',company,finance_book)) + (tinh_No_Cua_Yearly(nam,'221%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'222%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'2292%%',company,finance_book) + (tinh_No_Cua_Yearly(nam,'12813%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12822%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'12883%%',company,finance_book))) + tinh_No_Cua_Yearly(nam,'2422%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'243%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'22882%%',company,finance_book))
		elif maso == '300':
			return tinh_Co_Cua_Yearly(nam,'3311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'1311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'333%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'334%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3351%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'33621%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33631%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33681%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'337%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33871%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'3381%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3382%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3383%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3384%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33851%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3386%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33881%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'138%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3441%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'34111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34121%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343111%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'35211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35221%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35231%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35241%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'353%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'357%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'171%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3312%%',company,finance_book) + tinh_Co_Cua_Yearly_Select_If(nam,'1312%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3352%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3361%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'33622%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33632%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33682%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'33872%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'3442%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33852%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33882%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'34112%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34122%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343112%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'34312%%',company,finance_book)  + tinh_Co_Cua_Yearly(nam,'34313%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'3432%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'411122%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'347%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'35212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35222%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35232%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35242%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'356%%',company,finance_book)
		elif maso == '310':
			return tinh_Co_Cua_Yearly(nam,'3311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'1311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'333%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'334%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3351%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'33621%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33631%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33681%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'337%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33871%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'3381%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3382%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3383%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3384%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33851%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3386%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33881%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'138%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3441%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'34111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34121%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343111%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'35211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35221%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35231%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35241%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'353%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'357%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'171%%',company,finance_book)
		elif maso == '311':
			return tinh_Co_Cua_Yearly_Select_If(nam,'3311%%',company,finance_book)
		elif maso == '312':
			return tinh_Co_Cua_Yearly_Select_If(nam,'1311%%',company,finance_book)
		elif maso == '313':
			return tinh_Co_Cua_Yearly(nam,'333%%',company,finance_book)
		elif maso == '314':
			return tinh_Co_Cua_Yearly(nam,'334%%',company,finance_book)
		elif maso == '315':
			return tinh_Co_Cua_Yearly(nam,'3351%%',company,finance_book)
		elif maso == '316':
			return tinh_Co_Cua_Yearly(nam,'33621%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33631%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33681%%',company,finance_book)
		elif maso == '317':
			return tinh_Co_Cua_Yearly_Select_If(nam,'337%%',company,finance_book)
		elif maso == '318':
			return tinh_Co_Cua_Yearly(nam,'33871%%',company,finance_book)*2
		elif maso == '319':
			return tinh_Co_Cua_Yearly(nam,'3381%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3382%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3383%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3384%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33851%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3386%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33881%%',company,finance_book) + tinh_Co_Cua_Yearly_Select_If(nam,'1381%%',company,finance_book) + tinh_Co_Cua_Yearly_Select_If(nam,'13851%%',company,finance_book) +  tinh_Co_Cua_Yearly_Select_If(nam,'13881%%',company,finance_book) +  tinh_Co_Cua_Yearly(nam,'3441%%',company,finance_book) 
		elif maso == '320':
			return tinh_Co_Cua_Yearly(nam,'34111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34121%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343111%%',company,finance_book)
		elif maso == '321':
			return tinh_Co_Cua_Yearly(nam,'35211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35221%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35231%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35241%%',company,finance_book)
		elif maso == '322':
			return tinh_Co_Cua_Yearly(nam,'353%%',company,finance_book)
		elif maso == '323':
			return tinh_Co_Cua_Yearly(nam,'357%%',company,finance_book)
		elif maso == '324':
			return tinh_Co_Cua_Yearly(nam,'171%%',company,finance_book)
		elif maso == '330':
			return tinh_Co_Cua_Yearly(nam,'3312%%',company,finance_book) + tinh_Co_Cua_Yearly_Select_If(nam,'1312%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3352%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3361%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'33622%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33632%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33682%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'33872%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'3442%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33852%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33882%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'34112%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34122%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343112%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'34312%%',company,finance_book)  + tinh_Co_Cua_Yearly(nam,'34313%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'3432%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'411122%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'347%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'35212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35222%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35232%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35242%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'356%%',company,finance_book)
		elif maso == '331':
			return tinh_Co_Cua_Yearly(nam,'3312%%',company,finance_book)
		elif maso == '332':
			return tinh_No_Cua_Yearly_Select_If(nam,'1312%%',company,finance_book)
		elif maso == '333':
			return tinh_Co_Cua_Yearly(nam,'3352%%',company,finance_book)
		elif maso == '334':
			return tinh_Co_Cua_Yearly(nam,'3361%%',company,finance_book)
		elif maso == '335':
			return tinh_Co_Cua_Yearly(nam,'33622%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33632%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33682%%',company,finance_book)
		elif maso == '336':
			return tinh_Co_Cua_Yearly(nam,'33872%%',company,finance_book)
		elif maso == '337':
			return tinh_Co_Cua_Yearly(nam,'3442%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33852%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33882%%',company,finance_book)
		elif maso == '338':
			return tinh_Co_Cua_Yearly(nam,'34112%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34122%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343112%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'34312%%',company,finance_book)  + tinh_Co_Cua_Yearly(nam,'34313%%',company,finance_book)
		elif maso == '339':
			return tinh_Co_Cua_Yearly(nam,'3432%%',company,finance_book)
		elif maso == '340':
			return tinh_Co_Cua_Yearly(nam,'411122%%',company,finance_book)
		elif maso == '341':
			return tinh_Co_Cua_Yearly(nam,'347%%',company,finance_book)
		elif maso == '342':
			return tinh_Co_Cua_Yearly(nam,'35212%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35222%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35232%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35242%%',company,finance_book)
		elif maso == '343':
			return tinh_Co_Cua_Yearly(nam,'356%%',company,finance_book)
		elif maso == '400':
			return ((tinh_Co_Cua_Yearly(nam,'41111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'411121%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4112%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'4113%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'419%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'412%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'413%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'414%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'417%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book) ) + (tinh_Co_Cua_Yearly(nam,'4211%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4212%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'441%%',company,finance_book)) + ((tinh_Co_Cua_Yearly(nam,'461%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'161%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'466%%',company,finance_book)))
		elif maso == '410':
			return (tinh_Co_Cua_Yearly(nam,'41111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'411121%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4112%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'4113%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'419%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'412%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'413%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'414%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'417%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book) ) + (tinh_Co_Cua_Yearly(nam,'4211%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4212%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'441%%',company,finance_book)
		elif maso == '411':
			return tinh_Co_Cua_Yearly(nam,'41111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'411121%%',company,finance_book)
		elif maso == '411a':
			return tinh_Co_Cua_Yearly(nam,'41111%%',company,finance_book)
		elif maso == '411b':
			return tinh_Co_Cua_Yearly(nam,'411121%%',company,finance_book)
		elif maso == '412':
			return tinh_Co_Cua_Yearly(nam,'4112%%',company,finance_book)
		elif maso == '413':
			return tinh_Co_Cua_Yearly(nam,'4113%%',company,finance_book)
		elif maso == '414':
			return tinh_Co_Cua_Yearly(nam,'4118%%',company,finance_book)
		elif maso == '415':
			return tinh_Co_Cua_Yearly(nam,'419%%',company,finance_book)
		elif maso == '416':
			return tinh_Co_Cua_Yearly(nam,'412%%',company,finance_book)
		elif maso == '417':
			return tinh_Co_Cua_Yearly(nam,'413%%',company,finance_book)
		elif maso == '418':
			return tinh_Co_Cua_Yearly(nam,'414%%',company,finance_book)
		elif maso == '419':
			return tinh_Co_Cua_Yearly(nam,'417%%',company,finance_book)
		elif maso == '420':
			return tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book)
		elif maso == '421':
			return (tinh_Co_Cua_Yearly(nam,'4211%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4212%%',company,finance_book))
		elif maso == '421a':
			return tinh_Co_Cua_Yearly(nam,'4211%%',company,finance_book)
		elif maso == '421b':
			return tinh_Co_Cua_Yearly_Finance_Book(nam,'4212%%',company,finance_book)
		elif maso == '422':
			return tinh_Co_Cua_Yearly(nam,'441%%',company,finance_book)
		elif maso == '430':
			return (tinh_Co_Cua_Yearly(nam,'461%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'161%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'466%%',company,finance_book))
		elif maso == '431':
			return tinh_Co_Cua_Yearly(nam,'461%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'161%%',company,finance_book)
		elif maso == '432':
			return tinh_Co_Cua_Yearly(nam,'466%%',company,finance_book)
		elif maso == '440':
			return (tinh_Co_Cua_Yearly(nam,'3311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'1311%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'333%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'334%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3351%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'33621%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33631%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33681%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'337%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33871%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'3381%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3382%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3383%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3384%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33851%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3386%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'33881%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'138%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'3441%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'34111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34121%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343111%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'35211%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35221%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35231%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'35241%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'353%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'357%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'171%%',company,finance_book) + (tinh_Co_Cua_Yearly(nam,'34111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'34121%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'343111%%',company,finance_book))) + (((tinh_Co_Cua_Yearly(nam,'41111%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'411121%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4112%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'4113%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book) + tinh_No_Cua_Yearly(nam,'419%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'412%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'413%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'414%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'417%%',company,finance_book) + tinh_Co_Cua_Yearly(nam,'418%%',company,finance_book) ) + (tinh_Co_Cua_Yearly(nam,'4211%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'4212%%',company,finance_book)) + tinh_Co_Cua_Yearly(nam,'441%%',company,finance_book)) + ((tinh_Co_Cua_Yearly(nam,'461%%',company,finance_book) - tinh_No_Cua_Yearly(nam,'161%%',company,finance_book)) + (tinh_Co_Cua_Yearly(nam,'466%%',company,finance_book))))
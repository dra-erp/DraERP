# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
# Author: Nghĩa+Phát 

import functools
import math
import re
from erpnext.accounts.doctype import finance_book

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, flt, formatdate, get_first_day, getdate

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency
from erpnext.accounts.utils import get_fiscal_year

# Ham lay danh sach ngay duoc chon
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

	#Lay danh sach danh muc va ma so
	accounts = get_accounts()
	if not accounts:
		return None
	out = prepare_data(accounts, period_list,finance_book,company)
	return out

#Ham lay danh sach du lieu 
def prepare_data(accounts, period_list,finance_book,company):
	data = []

	for d in accounts:
		# add to output
		has_value = False
		total = 0
		row = frappe._dict({
			"chi_tieu": d.chi_tieu,
			"ma_so": d.ma_so
		})
		for period in period_list:

			row[period.key] = get_giatri(period,d.ma_so,period.periodicity,finance_book,company)
			if get_giatri(period,d.ma_so,period.periodicity,finance_book,company):
				total += row[period.key]


		row["total"] = total
		data.append(row)

		

	return data
#Tinh Sum Co Cua TK neu chon option la Yearly
def tinh_Co_Cua_Yearly(nam,account,company):
	test={
		"nam":nam,
		"account":account,
		"company":company
	}
	return flt(frappe.db.sql("""
			select sum(credit)-sum(debit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
def tinh_Co_Cua_Yearly_711(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":frappe.get_cached_value('Company',company,  "default_finance_book")
	}
	if finance_book==frappe.get_cached_value('Company',company,  "default_finance_book"):
		return flt(frappe.db.sql("""
				select sum(credit)-sum(debit) from `tabGL Entry` as gle
				where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)			
	else:
		return flt(frappe.db.sql("""
				select sum(credit)-sum(debit) from `tabGL Entry` as gle
				where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)-flt(frappe.db.sql("""
				select sum(credit)-sum(debit) from `tabGL Entry` as gle
				where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s and gle.finance_book like %(finance_book)s""",test,as_list=True)[0][0],2)	
def tinh_No_Cua_Yearly(nam,account,company):
	test={
		"nam":nam,
		"account":account,
		"company":company
	}
	return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)

def tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"finance_book":finance_book,
		"company":company
	}
	if finance_book==frappe.get_cached_value('Company',company,  "default_finance_book"):
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
	else:
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s AND ( gle.finance_book IS NULL OR gle.finance_book='') """,test,as_list=True)[0][0],2)

def tinh_No_Cua_Yearly_Cua_TK6424(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"finance_book":finance_book,
		"company":company
	}
	if finance_book:
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s AND ( gle.finance_book IS NULL OR gle.finance_book='') """,test,as_list=True)[0][0],2)+flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s and gle.finance_book like %(finance_book)s """,test,as_list=True)[0][0],2)
	else:
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s AND ( gle.finance_book IS NULL OR gle.finance_book='') """,test,as_list=True)[0][0],2)

def tinh_No_Cua_Yearly_Cua_TK6427(nam,account,company,finance_book):
	test={
		"nam":nam,
		"account":account,
		"finance_book":finance_book,
		"company":company
	}

	return flt(frappe.db.sql("""
		select sum(debit)-sum(credit) from `tabGL Entry` as gle
		where gle.account like %(account)s and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
		and gle.company like %(company)s""",test,as_list=True)[0][0],2)

def tinh_No_Cua_Yearly_Cua_TK6428(nam,account,company,finance_book):
	test={
		"nam":nam,
		"company":company,
		"finance_book_default":frappe.get_cached_value('Company',company,  "default_finance_book")
	}
	if finance_book==frappe.get_cached_value('Company',company,  "default_finance_book"):
		return flt(frappe.db.sql("""
				select sum(debit)-sum(credit) from `tabGL Entry` as gle
				where gle.account like '6428%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)
	else:
		return flt(frappe.db.sql("""
				select sum(debit)-sum(credit) from `tabGL Entry` as gle
				where gle.account like '6428%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)-flt(frappe.db.sql("""
				select sum(debit)-sum(credit) from `tabGL Entry` as gle
				where gle.account like '6428%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s and gle.finance_book like %(finance_book_default)s""",test,as_list=True)[0][0],2)
def tinh_Co_Khac_Yearly(nam,account,company):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company
	}
	return flt(frappe.db.sql("""
			select sum(credit)-sum(debit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
def tinh_Co_Khac_Yearly_711(nam,account,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company,
		"finance_book":frappe.get_cached_value('Company',company,  "default_finance_book")
	}
	if finance_book==frappe.get_cached_value('Company',company,  "default_finance_book"):
		return flt(frappe.db.sql("""
				select sum(credit)-sum(debit) from `tabGL Entry` as gle
				where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)			
	else:
		return flt(frappe.db.sql("""
				select sum(credit)-sum(debit) from `tabGL Entry` as gle
				where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)-flt(frappe.db.sql("""
				select sum(credit)-sum(debit) from `tabGL Entry` as gle
				where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s and gle.finance_book like %(finance_book)s""",test,as_list=True)[0][0],2)	
def tinh_No_Khac_Yearly(nam,account,company):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company
	}
	return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
def tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,account,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"finance_book":finance_book,
		"company":company
	}
	if finance_book==frappe.get_cached_value('Company',company,  "default_finance_book"):
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
	else:
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s AND ( gle.finance_book IS NULL OR gle.finance_book='') """,test,as_list=True)[0][0],2)

def tinh_No_Khac_Yearly_Cua_TK6424(nam,account,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"finance_book":finance_book,
		"company":company
	}
	if finance_book:
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s AND ( gle.finance_book IS NULL OR gle.finance_book='') """,test,as_list=True)[0][0],2)+flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s and gle.finance_book like %(finance_book)s """,test,as_list=True)[0][0],2)
	else:
		return flt(frappe.db.sql("""
			select sum(debit)-sum(credit) from `tabGL Entry` as gle
			where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s AND ( gle.finance_book IS NULL OR gle.finance_book='') """,test,as_list=True)[0][0],2)

def tinh_No_Khac_Yearly_Cua_TK6427(nam,account,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"finance_book":finance_book,
		"company":company
	}

	return flt(frappe.db.sql("""
		select sum(debit)-sum(credit) from `tabGL Entry` as gle
		where gle.account like %(account)s and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
		and gle.company like %(company)s""",test,as_list=True)[0][0],2)

def tinh_No_Khac_Yearly_Cua_TK6428(nam,account,company,finance_book):
	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"finance_book":finance_book,
		"company":company,
		"finance_book_default":frappe.get_cached_value('Company',company,  "default_finance_book")
	}
	if finance_book==frappe.get_cached_value('Company',company,  "default_finance_book"):
		return flt(frappe.db.sql("""
				select sum(debit)-sum(credit) from `tabGL Entry` as gle
				where gle.account like '6428%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)
	else:
		return flt(frappe.db.sql("""
				select sum(debit)-sum(credit) from `tabGL Entry` as gle
				where gle.account like '6428%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s""",test,as_list=True)[0][0],2)-flt(frappe.db.sql("""
				select sum(debit)-sum(credit) from `tabGL Entry` as gle
				where gle.account like '6428%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
				and gle.company like %(company)s and gle.finance_book like %(finance_book_default)s""",test,as_list=True)[0][0],2)

def get_giatri(nam,maso,periodicity,finance_book,company):
	#Kiem tra neu chon option la Yearly thi thuc hien
	if periodicity=="Yearly":
		nam=nam.label
		if maso==1:
			#Goi ham tinh gia tri
			return tinh_Co_Cua_Yearly(nam,'511%%',company)
		elif maso==2:
			return tinh_No_Cua_Yearly(nam,'521%%',company)
		elif maso==10:
			return tinh_Co_Cua_Yearly(nam,'511%%',company)-tinh_No_Cua_Yearly(nam,'521%%',company)
		elif maso==11:
			return tinh_No_Cua_Yearly(nam,'632%%',company)
		elif maso==20:
			return (tinh_Co_Cua_Yearly(nam,'511%%',company)-tinh_No_Cua_Yearly(nam,'521%%',company))-tinh_No_Cua_Yearly(nam,'632%%',company)
		elif maso==21:
			return tinh_Co_Cua_Yearly(nam,'515%%',company)
		elif maso==22:
			return tinh_No_Cua_Yearly(nam,'635%%',company)
		elif maso==25:
			return tinh_No_Cua_Yearly(nam,'641%%',company)
		elif maso==26:
			#Tk 642 se chia ra la 6428, 6423, 6427 co anh huong boi finance_book va TK6421, 6422 khong anh huong boi finanace_book
			return (tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6428(nam,'6428%',company,finance_book))
		elif maso==30:
			return ((tinh_Co_Cua_Yearly(nam,'511%%',company)-tinh_No_Cua_Yearly(nam,'521%%',company))-tinh_No_Cua_Yearly(nam,'632%%',company))+tinh_Co_Cua_Yearly(nam,'515%%',company)-tinh_No_Cua_Yearly(nam,'635%%',company)-tinh_No_Cua_Yearly(nam,'641%%',company)-(tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6428(nam,'6428%',company,finance_book))
		elif maso==31:
			return tinh_Co_Cua_Yearly_711(nam,'711%%',company,finance_book)
		elif maso==32:
			return tinh_No_Cua_Yearly(nam,'811%%',company)
		elif maso==40:
			return tinh_Co_Cua_Yearly_711(nam,'711%%',company,finance_book)-tinh_No_Cua_Yearly(nam,'811%%',company)
		elif maso==50:
			return (((tinh_Co_Cua_Yearly(nam,'511%%',company)-tinh_No_Cua_Yearly(nam,'521%%',company))-tinh_No_Cua_Yearly(nam,'632%%',company))+tinh_Co_Cua_Yearly(nam,'515%%',company)-tinh_No_Cua_Yearly(nam,'635%%',company)-tinh_No_Cua_Yearly(nam,'641%%',company)-(tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6428(nam,'6428%',company,finance_book)))+(tinh_Co_Cua_Yearly_711(nam,'711%%',company,finance_book)-tinh_No_Cua_Yearly(nam,'811%%',company))
		elif maso==51:
			test={
				"nam":nam,
				"company":company
			}
			return flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8211%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
		elif maso==52:
			test={
				"nam":nam,
				"company":company
			}
			return flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8212%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)
		elif maso==60:
			test={
				"nam":nam,
				"company":company
			}
			return (((tinh_Co_Cua_Yearly(nam,'511%%',company)-tinh_No_Cua_Yearly(nam,'521%%',company))-tinh_No_Cua_Yearly(nam,'632%%',company))+tinh_Co_Cua_Yearly(nam,'515%%',company)-tinh_No_Cua_Yearly(nam,'635%%',company)-tinh_No_Cua_Yearly(nam,'641%%',company)-(tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Cua_Yearly_Cua_TK6428(nam,'6428%',company,finance_book)))+(tinh_Co_Cua_Yearly_711(nam,'711%%',company,finance_book)-tinh_No_Cua_Yearly(nam,'811%%',company))-(flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8211%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2)+flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8212%%' and gle.fiscal_year=%(nam)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test,as_list=True)[0][0],2))
	else:
		test2={
			"from_date":nam.from_date,
			"to_date":nam.to_date,
			"company":company
		}
		if maso==1:
			return tinh_Co_Khac_Yearly(nam,'511%%',company)
		elif maso==2:
			return tinh_No_Khac_Yearly(nam,'521%%',company)
		elif maso==10:
			return tinh_Co_Khac_Yearly(nam,'511%%',company)-tinh_No_Khac_Yearly(nam,'521%%',company)
		elif maso==11:
			return tinh_No_Khac_Yearly(nam,'632%%',company)
		elif maso==20:
			return (tinh_Co_Khac_Yearly(nam,'511%%',company)-tinh_No_Khac_Yearly(nam,'521%%',company))-tinh_No_Khac_Yearly(nam,'632%%',company)
		elif maso==21:
			return tinh_Co_Khac_Yearly(nam,'515%%',company)
		elif maso==22:
			return tinh_No_Khac_Yearly(nam,'635%%',company)
		elif maso==25:
			return tinh_No_Khac_Yearly(nam,'641%%',company)
		elif maso==26:
			return (tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6428(nam,'6428%',company,finance_book))
		elif maso==30:
			return ((tinh_Co_Khac_Yearly(nam,'511%%',company)-tinh_No_Khac_Yearly(nam,'521%%',company))-tinh_No_Khac_Yearly(nam,'632%%',company))+tinh_Co_Khac_Yearly(nam,'515%%',company)-tinh_No_Khac_Yearly(nam,'635%%',company)-tinh_No_Khac_Yearly(nam,'641%%',company)-(tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6428(nam,'6428%',company,finance_book))
		elif maso==31:
			return tinh_Co_Khac_Yearly_711(nam,'711%%',company,finance_book)
		elif maso==32:
			return tinh_No_Khac_Yearly(nam,'811%%',company)
		elif maso==40:
			return tinh_Co_Khac_Yearly_711(nam,'711%%',company,finance_book)-tinh_No_Khac_Yearly(nam,'811%%',company)
		elif maso==50:
			return (((tinh_Co_Khac_Yearly(nam,'511%%',company)-tinh_No_Khac_Yearly(nam,'521%%',company))-tinh_No_Khac_Yearly(nam,'632%%',company))+tinh_Co_Khac_Yearly(nam,'515%%',company)-tinh_No_Khac_Yearly(nam,'635%%',company)-tinh_No_Khac_Yearly(nam,'641%%',company)-(tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6428(nam,'6428%',company,finance_book)))+(tinh_Co_Khac_Yearly_711(nam,'711%%',company,finance_book)-tinh_No_Khac_Yearly(nam,'811%%',company))
		elif maso==51:
			return flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8211%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test2,as_list=True)[0][0],2)
		elif maso==52:
			return flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8212%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test2,as_list=True)[0][0],2)
		elif maso==60:
			return (((tinh_Co_Khac_Yearly(nam,'511%%',company)-tinh_No_Khac_Yearly(nam,'521%%',company))-tinh_No_Khac_Yearly(nam,'632%%',company))+tinh_Co_Khac_Yearly(nam,'515%%',company)-tinh_No_Khac_Yearly(nam,'635%%',company)-tinh_No_Khac_Yearly(nam,'641%%',company)-(tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6421%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6421_6423(nam,'6423%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6424(nam,'6424%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6427(nam,'6427%',company,finance_book)+tinh_No_Khac_Yearly_Cua_TK6428(nam,'6428%',company,finance_book)))+(tinh_Co_Khac_Yearly_711(nam,'711%%',company,finance_book)-tinh_No_Khac_Yearly(nam,'811%%',company))-(flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8211%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test2,as_list=True)[0][0],2)+flt(frappe.db.sql("""
			select (sum(debit)-sum(credit)) from `tabGL Entry` as gle
			where gle.account like '8212%%' and gle.posting_date >= %(from_date)s and gle.posting_date<= %(to_date)s and gle.voucher_type not like 'Period Closing Voucher'
			and gle.company like %(company)s""",test2,as_list=True)[0][0],2))

#Ham lay danh sach chi tieu va ma so
def get_accounts():
	return frappe.db.sql("""
		select chi_tieu, ma_so
		from `tabDOLIBAR` order by ma_so
		""",as_dict=True)

#Ham tao danh sach colmn luc hien thi
def get_columns(periodicity, period_list, accumulated_values=1, company=None):
	columns = [{
		"fieldname": "chi_tieu",
		"label": "Chi Tieu",
		"fieldtype": "Data",
		"options": "DOLIBAR",
		"width": 400
	},
	{
		"fieldname": "ma_so",
		"label": "Ma So",
		"fieldtype": "Data",
		"options": "DOLIBAR",
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


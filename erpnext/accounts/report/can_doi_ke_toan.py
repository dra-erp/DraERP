# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from calendar import c
from cgi import test
import functools
import math
import re
from unicodedata import name
from braintree import TransactionSearch

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, flt, formatdate, get_first_day, getdate, list_to_str
from pymysql import NULL

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
        for i in range(len(period_list)): 
            row[period_list[i].key] = get_giatri(period_list[i],d.maso,period_list[i].periodicity,company,finance_book)
            total += row[period_list[i].key]
        row["total"] = total
        data.append(row)
    return data
#####Test######


### Hàm tính Nợ - Có của năm có Finance book isNull
def tinh_No_Cua_Yearly_Finance_Book_isNull(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return flt(frappe.db.sql("""
			select sum(debit)-sum(credit)
			from `tabGL Entry` as gle
			where (gle.account LIKE %(account)s)
				and (gle.company = %(company)s)
				and (gle.finance_book is null or gle.finance_book =''  )
				and (gle.fiscal_year between 2000 AND %(nam)s)
			""",test,as_list=True)[0][0],2)			
def tinh_Co_Cua_Yearly_Finance_Book_isNull(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and (gle.finance_book is null or gle.finance_book ='' )
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)

## Hàm tính Nợ - Có của năm có Finance book
def tinh_No_Cua_Yearly_Finance_Book(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return (flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)
                    + tinh_No_Cua_Yearly_Finance_Book_isNull(nam,account,company,finance_book))

def tinh_Co_Cua_Yearly_Finance_Book(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return (flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)
                    + tinh_Co_Cua_Yearly_Finance_Book_isNull(nam,account,company,finance_book))
### Hàm với điều kiện > 0 có Finance book
def tinh_No_Cua_Yearly_If_Pos(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = flt(frappe.db.sql("""
			select sum(debit)-sum(credit)
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)
    b = flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s 
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)      
    if a > 0:
        return a + b
    else:
        return 0


def tinh_No_Cua_Yearly_If_Pos_ma153(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = frappe.db.sql("""
			select (sum(debit)-sum(credit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.fiscal_year between 2000 AND %(nam)s
				group by Account having total > 0""",test,as_dict=True)  
    ma153 = 0
    for party in a :
        ma153+=party.total  
    return ma153 
def tinh_No_Cua_Yearly_If_Pos_ma313(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = frappe.db.sql("""
			select (sum(debit)-sum(credit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.fiscal_year between 2000 AND %(nam)s
				group by Account having total > 0""",test,as_dict=True)  
    ma313 = 0
    for party in a :
        ma313+=party.total  
    return ma313 

def tinh_Co_Cua_Yearly_If_Pos_ma313(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = frappe.db.sql("""
			select (sum(credit)-sum(debit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.fiscal_year between 2000 AND %(nam)s
				group by Account having total > 0""",test,as_dict=True)  
    ma313 = 0
    for party in a :
        ma313+=party.total  
    return ma313 



def tinh_Co_Cua_Yearly_If_Pos(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = flt(frappe.db.sql("""
			select sum(credit)-sum(debit)
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)
    b = flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
				and gle.fiscal_year between 2000 AND %(nam)s
			""",test,as_list=True)[0][0],2)      
    if a > 0:
        return a + b
    else:
        return 0	

## Điều kiện Nợ - Có luôn âm có finance_book
def tinh_No_Cua_Yearly_If_Nega(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company, "default_finance_book")
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = (flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where (gle.account like %(account)s) 
				AND (gle.company = %(company)s)
				AND (gle.finance_book = %(finance_book)s)
				AND (gle.fiscal_year between 2000 and %(nam)s) 
			""",test,as_list=True)[0][0],2)
                    + tinh_No_Cua_Yearly_Finance_Book_isNull(nam,account,company,finance_book))
    if a>0:
        return -a
    else:
        return a
def tinh_Co_Cua_Yearly_If_Nega(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company, "default_finance_book")
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = (flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where (gle.account like %(account)s) 
				and (gle.company = %(company)s)
				and (gle.finance_book = %(finance_book)s)
				and (gle.fiscal_year between 2000 and %(nam)s) 
			""",test,as_list=True)[0][0],2)
                    + tinh_Co_Cua_Yearly_Finance_Book_isNull(nam,account,company,finance_book))
    if a > 0:
        return -a
    else:
        return a

### Lấy dữ liệu Nợ - Có lấy dương của Party có Finance book
def tinh_No_Yearly_Finance_Book_Party_Pos(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    list = frappe.db.sql("""
    		select (sum(debit)-sum(credit)) total
    		from `tabGL Entry` as gle
    		where gle.account LIKE %(account)s
    			and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and is_cancelled = 0
    			and (gle.fiscal_year between 2000 AND %(nam)s or ifnull(is_opening, 'No') = 'Yes')
    			group by account,party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
			select (sum(debit)-sum(credit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and is_cancelled = 0
				and (gle.fiscal_year between 2000 AND %(nam)s or ifnull(is_opening, 'No') = 'Yes')
				group by account,party having total > 0""",test,as_dict=True)  
    Prt = 0
    for party in list :
        Prt+=party.total  
    for party in a :
        Prt+=party.total  
    return Prt 

def tinh_Co_Yearly_Finance_Book_Party_Pos(nam,account,company,finance_book):
    test={
            "nam":nam,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    list = frappe.db.sql("""
    		SELECT 
		ACCOUNT,party,(SUM(credit)-SUM(debit)) AS total
		from `tabGL Entry`
		where
			company=%(company)s
			AND (account LIKE %(account)s
				)
            and finance_book = %(finance_book)s 
			and is_cancelled = 0
			AND fiscal_year<=%(nam)s
			GROUP BY account,party
			HAVING total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
			SELECT 
		ACCOUNT,party,(SUM(credit)-SUM(debit)) AS total
		from `tabGL Entry`
		where
			company=%(company)s
			AND (account LIKE %(account)s
				)

			and is_cancelled = 0
			AND fiscal_year<=%(nam)s
			GROUP BY account,party
			HAVING total > 0
            """,test,as_dict=True)  
    Prt = 0
    for party in list :
        Prt+=party.total  
    for party in a :
        Prt+=party.total  
    return Prt

# PostingDate_FinanceBook
### Hàm tính Nợ - Có của năm có Finance book isNull PostingDate
def tinh_No_Yearly_Finance_Book_isNull_PostingDate_Opening(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return flt(frappe.db.sql("""
			select sum(debit)-sum(credit)
			from `tabGL Entry` as gle
			where (gle.account LIKE %(account)s)
				and (gle.company = %(company)s)
				and (gle.finance_book is null or gle.finance_book ='' ) 
                and (gle.posting_date<= %(to_date)s)
			""",test,as_list=True)[0][0],2)	
def tinh_No_Yearly_Finance_Book_isNull_PostingDate_Mid(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return flt(frappe.db.sql("""
			select sum(debit)-sum(credit)
			from `tabGL Entry` as gle
			where (gle.account LIKE %(account)s)
				and (gle.company = %(company)s)
				and (gle.finance_book is null or gle.finance_book ='' ) 
                and (gle.posting_date<= %(to_date)s)
                and (gle.posting_date>= %(from_date)s)
			""",test,as_list=True)[0][0],2)
def tinh_Co_Yearly_Finance_Book_isNull_PostingDate_Opening(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return flt(frappe.db.sql("""
			select sum(credit)-sum(debit)
			from `tabGL Entry` as gle
			where (gle.account LIKE %(account)s)
				and (gle.company = %(company)s)
				and (gle.finance_book is null or gle.finance_book ='' ) 
                and (gle.posting_date<= %(to_date)s)
			""",test,as_list=True)[0][0],2)	
def tinh_Co_Yearly_Finance_Book_isNull_PostingDate_Mid(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return flt(frappe.db.sql("""
			select sum(credit)-sum(debit)
			from `tabGL Entry` as gle
			where (gle.account LIKE %(account)s)
				and (gle.company = %(company)s)
				and (gle.finance_book is null or gle.finance_book ='' ) 
                and (gle.posting_date<= %(to_date)s)
                and (gle.posting_date>= %(from_date)s)
			""",test,as_list=True)[0][0],2)
## Hàm tính Nợ - Có của năm có Finance book PostingDate
def tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return (flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_No_Yearly_Finance_Book_isNull_PostingDate_Opening(nam,account,company,finance_book))

def tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return (flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_No_Yearly_Finance_Book_isNull_PostingDate_Mid(nam,account,company,finance_book))

def tinh_Co_Yearly_Finance_Book_PostingDate_Opening(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return (flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_Co_Yearly_Finance_Book_isNull_PostingDate_Opening(nam,account,company,finance_book))

def tinh_Co_Yearly_Finance_Book_PostingDate_Mid(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company,  "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    return (flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_Co_Yearly_Finance_Book_isNull_PostingDate_Mid(nam,account,company,finance_book))

### Hàm với điều kiện > 0 có Finance book
def tinh_No_Yearly_Pos_PostingDate_Opening(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = flt(frappe.db.sql("""
			select sum(debit)-sum(credit)
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
    b = flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)      
    if a > 0:
        return a + b
    else:
        return 0
def tinh_No_Yearly_Pos_PostingDate_Mid(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = flt(frappe.db.sql("""
			select sum(debit)-sum(credit)
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
    b = flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)      
    if a > 0:
        return a + b
    else:
        return 0

def tinh_Co_Yearly_Pos_PostingDate_Opening(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = flt(frappe.db.sql("""
			select sum(credit)-sum(debit)
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
    b = flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)      
    if a > 0:
        return a + b
    else:
        return 0
def tinh_Co_Yearly_Pos_PostingDate_Mid(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = flt(frappe.db.sql("""
			select sum(credit)-sum(debit)
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
    b = flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
				and gle.finance_book=%(finance_book)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)      
    if a > 0:
        return a + b
    else:
        return 0		

## Điều kiện Nợ - Có luôn âm có finance_book
def tinh_No_Yearly_Nega_PostingDate_Opening(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company, "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = (flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where (gle.account like %(account)s) 
				AND (gle.company = %(company)s)
				AND (gle.finance_book = %(finance_book)s)
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_No_Yearly_Finance_Book_isNull_PostingDate_Opening(nam,account,company,finance_book))
    if a>0:
        return -a
    else:
        return a
def tinh_No_Yearly_Nega_PostingDate_Mid(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company, "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = (flt(frappe.db.sql("""
			select sum(debit)-sum(credit) 
			from `tabGL Entry` as gle
			where (gle.account like %(account)s) 
				AND (gle.company = %(company)s)
				AND (gle.finance_book = %(finance_book)s)
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_No_Yearly_Finance_Book_isNull_PostingDate_Mid(nam,account,company,finance_book))
    if a>0:
        return -a
    else:
        return a
def tinh_Co_Yearly_Nega_PostingDate_Opening(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company, "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = (flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where (gle.account like %(account)s) 
				and (gle.company = %(company)s)
				and (gle.finance_book = %(finance_book)s)
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_Co_Yearly_Finance_Book_isNull_PostingDate_Opening(nam,account,company,finance_book))
    if a > 0:
        return -a
    else:
        return a
def tinh_Co_Yearly_Nega_PostingDate_Mid(nam,account,company,finance_book):
    if finance_book: 
        finance_book=finance_book
    else:
        finance_book=frappe.get_cached_value('Company',company, "default_finance_book")
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    a = (flt(frappe.db.sql("""
			select sum(credit)-sum(debit) 
			from `tabGL Entry` as gle
			where (gle.account like %(account)s) 
				and (gle.company = %(company)s)
				and (gle.finance_book = %(finance_book)s)
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
			""",test,as_list=True)[0][0],2)
                    + tinh_Co_Yearly_Finance_Book_isNull_PostingDate_Mid(nam,account,company,finance_book))
    if a > 0:
        return -a
    else:
        return a

### Lấy dữ liệu Nợ - Có lấy dương của Party có Finance book
def tinh_No_Yearly_Party_Pos_PostingDate_Opening(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    list = frappe.db.sql("""
    		select (sum(debit)-sum(credit)) total
    		from `tabGL Entry` as gle
    		where gle.account LIKE %(account)s
    			and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and gle.posting_date<= %(to_date)s
    			group by party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
			select (sum(debit)-sum(credit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date<= %(to_date)s
				group by party having total > 0""",test,as_dict=True)  
    Prt = 0
    for party in list :
        Prt+=party.total  
    for party in a :
        Prt+=party.total  
    return Prt
def tinh_No_Yearly_Party_Pos_PostingDate_Mid(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    list = frappe.db.sql("""
    		select (sum(debit)-sum(credit)) total
    		from `tabGL Entry` as gle
    		where gle.account LIKE %(account)s
    			and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
    			group by party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
			select (sum(debit)-sum(credit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
				group by party having total > 0""",test,as_dict=True)  
    Prt = 0
    for party in list :
        Prt+=party.total  
    for party in a :
        Prt+=party.total  
    return Prt  

def tinh_Co_Yearly_Party_Pos_PostingDate_Opening(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    list = frappe.db.sql("""
    		select (sum(credit)-sum(debit)) total
    		from `tabGL Entry` as gle
    		where gle.account LIKE %(account)s
    			and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s 
                and gle.posting_date<= %(to_date)s
    			group by party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
			select (sum(credit)-sum(debit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date<= %(to_date)s
				group by party having total > 0""",test,as_dict=True)  
    Prt = 0
    for party in list :
        Prt+=party.total  
    for party in a :
        Prt+=party.total  
    return Prt
def tinh_Co_Yearly_Party_Pos_PostingDate_Mid(nam,account,company,finance_book):
    test={
	    	"from_date":nam.from_date,
		    "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book
    }
    list = frappe.db.sql("""
    		select (sum(credit)-sum(debit)) total
    		from `tabGL Entry` as gle
    		where gle.account LIKE %(account)s
    			and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s 
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
    			group by party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
			select (sum(credit)-sum(debit)) total
			from `tabGL Entry` as gle
			where gle.account LIKE %(account)s
				and gle.company = %(company)s
                and gle.posting_date>= %(from_date)s
                and gle.posting_date<= %(to_date)s
				group by party having total > 0""",test,as_dict=True)  
    Prt = 0
    for party in list :
        Prt+=party.total  
    for party in a :
        Prt+=party.total  
    return Prt
def get_accounts():
    return frappe.db.sql("""
		select taisan, maso
		from `tabBangCanDoiKeToan` order by maso
		""",as_dict=True)

### Lọc dữ liệu theo Company - PostingDate_FinanceBook
def locTheoCompany_PostingDate_FinanceBook(list,nam,company,fiannce_book):
	l=[]
	for i in list:
		if i.company==company and i.posting_date<=nam.to_date and i.posting_date>=nam.from_date:
			l.append(i)
	return l

def get_columns(periodicity, period_list, accumulated_values=1, company=True):
    columns = [{
            "fieldname": "taisan",
            "label": "Tai San",
            "fieldtype": "Data",
            "options": "BanganDoiKeToan",
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
    if periodicity== "Yearly":

        nam = nam.label



        KQma111=  ((tinh_No_Cua_Yearly_Finance_Book(nam,'111%%',company,finance_book)) 
                    + (tinh_No_Cua_Yearly_Finance_Book(nam,'112%%',company,finance_book)) 
                    + (tinh_No_Cua_Yearly_Finance_Book(nam,'113%%',company,finance_book)))
        KQma112=  (tinh_No_Cua_Yearly_Finance_Book(nam,'12811%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book(nam,'12881%%',company,finance_book))
        KQma110 = KQma111 + KQma112

        KQma121=  tinh_No_Cua_Yearly_Finance_Book(nam,'121%%',company,finance_book)
        KQma122=  tinh_Co_Cua_Yearly_If_Nega(nam,'2291%%',company,finance_book)
        KQma123=  (tinh_No_Cua_Yearly_Finance_Book(nam,'12812%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'12821%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'12882%%',company,finance_book))
        KQma120 = KQma121 + KQma122 + KQma123

        KQma131=   tinh_No_Yearly_Finance_Book_Party_Pos(nam,'1311%',company,finance_book)
        KQma132=   tinh_No_Yearly_Finance_Book_Party_Pos(nam,'3311%%',company,finance_book)
        KQma133=   (tinh_No_Cua_Yearly_Finance_Book(nam,'13621%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'13631%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'13681%%',company,finance_book))
        KQma134=   tinh_No_Cua_Yearly_If_Pos(nam,'337%%',company,finance_book)
        KQma135=   tinh_No_Cua_Yearly_Finance_Book(nam,'12831%%',company,finance_book)
        KQma136=   (tinh_No_Cua_Yearly_Finance_Book(nam,'1411%%',company,finance_book)
            + tinh_No_Cua_Yearly_Finance_Book(nam,'2441%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'13851%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'13881%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'334%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'3381%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'3382%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'3383%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'3384%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33851%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'3386%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33871%%',company,finance_book)
            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33881%%',company,finance_book)
            )
        KQma137=   tinh_Co_Cua_Yearly_If_Nega(nam,'22931%%',company,finance_book)
        KQma139=   tinh_No_Cua_Yearly_If_Pos(nam,'1381%%',company,finance_book)
        KQma130 =  KQma131 + KQma132 + KQma133 + KQma134 + KQma135 + KQma136 + KQma137 + KQma139


        KQma141=  (tinh_No_Cua_Yearly_Finance_Book(nam,'151%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'152%%',company,finance_book)
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'155%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'156%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'157%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'158%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'1531%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'1532%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'1533%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'15341%%',company,finance_book)
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'1541%%',company,finance_book) 
                            )
        KQma149=   tinh_No_Cua_Yearly_If_Nega(nam,'22941%%',company,finance_book)
        KQma140 = KQma141 + KQma149


        KQma151 = tinh_No_Cua_Yearly_Finance_Book(nam,'2421%%',company,finance_book)
        KQma152 = tinh_No_Cua_Yearly_Finance_Book(nam,'133%%',company,finance_book)
        KQma153 = tinh_No_Cua_Yearly_If_Pos_ma153(nam,'333%%',company,finance_book)
        KQma154 = tinh_No_Cua_Yearly_If_Pos(nam,'171%%',company,finance_book)
        KQma155 = tinh_No_Cua_Yearly_Finance_Book(nam,'22881%%',company,finance_book)
        KQma150 = KQma151 + KQma152 + KQma153 + KQma154 + KQma155

        KQma100= KQma110+KQma120+KQma130+KQma140+KQma150

        KQma211 = tinh_No_Yearly_Finance_Book_Party_Pos(nam,'1312%%',company,finance_book)
        KQma212 = tinh_No_Yearly_Finance_Book_Party_Pos(nam,'3312%%',company,finance_book)
        KQma213 = tinh_No_Cua_Yearly_Finance_Book(nam,'1361%%',company,finance_book)
        KQma214 = (tinh_No_Cua_Yearly_Finance_Book(nam,'13622%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'13632%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'13682%%',company,finance_book))
        KQma215 = tinh_No_Cua_Yearly_Finance_Book(nam,'12832%%',company,finance_book)
        KQma216 = (tinh_No_Cua_Yearly_If_Pos_ma313(nam,'13852%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'13882%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'1412%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'2442%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33852%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33872%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33882%%',company,finance_book))
        KQma219 = tinh_No_Cua_Yearly_If_Nega(nam,'22932%%',company,finance_book)

        KQma210 =  KQma211 + KQma212 + KQma213 + KQma214 + KQma215 + KQma216 + KQma219

        KQma222 = tinh_No_Cua_Yearly_Finance_Book(nam,'211%%',company,finance_book)
        KQma223 = tinh_Co_Cua_Yearly_If_Nega(nam,'2141%%',company,finance_book)
        KQma221 =  KQma222 + KQma223


        KQma225 = tinh_No_Cua_Yearly_Finance_Book(nam,'212%%',company,finance_book)
        KQma226 = tinh_Co_Cua_Yearly_If_Nega(nam,'2142%%',company,finance_book)
        KQma224 =  KQma225 + KQma226


        KQma228 = tinh_No_Cua_Yearly_Finance_Book(nam,'213%%',company,finance_book)
        KQma229 = tinh_Co_Cua_Yearly_If_Nega(nam,'2143%%',company,finance_book)
        KQma227 =  KQma228 + KQma229

        KQma220 =  KQma221 + KQma224 + KQma227

        KQma231 = tinh_No_Cua_Yearly_Finance_Book(nam,'217%%',company,finance_book)
        KQma232 = tinh_Co_Cua_Yearly_If_Nega(nam,'2147%%',company,finance_book)
        KQma230 =  KQma231 + KQma232


        KQma241 = (tinh_No_Cua_Yearly_Finance_Book(nam,'1542%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'22942%%',company,finance_book))
        KQma242 = tinh_No_Cua_Yearly_Finance_Book(nam,'241%%',company,finance_book)
        KQma240 =  KQma241 + KQma242


        KQma251 = tinh_No_Cua_Yearly_Finance_Book(nam,'221%%',company,finance_book)
        KQma252 = tinh_No_Cua_Yearly_Finance_Book(nam,'222%%',company,finance_book)
        KQma253 = tinh_No_Cua_Yearly_Finance_Book(nam,'2281%%',company,finance_book)
        KQma254 = tinh_Co_Cua_Yearly_If_Nega(nam,'2292%%',company,finance_book)
        KQma255 = (tinh_No_Cua_Yearly_Finance_Book(nam,'12813%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'12822%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'12883%%',company,finance_book))
        KQma250 =  KQma251 + KQma252 + KQma253 + KQma254 + KQma255

        KQma261 = tinh_No_Cua_Yearly_Finance_Book(nam,'2422%%',company,finance_book)
        KQma262 = tinh_No_Cua_Yearly_Finance_Book(nam,'243%%',company,finance_book)
        KQma263 = (tinh_No_Cua_Yearly_Finance_Book(nam,'22943%%',company,finance_book) 
                            + tinh_No_Cua_Yearly_Finance_Book(nam,'15342%%',company,finance_book))
        KQma268 = tinh_No_Cua_Yearly_Finance_Book(nam,'22882%%',company,finance_book)
        KQma260 =  KQma261 + KQma262 + KQma263 + KQma268

        KQma200 = KQma210 + KQma220 + KQma230 + KQma240 + KQma250 + KQma260

        KQma270 =  KQma100 + KQma200



        KQma311 = tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'3311%%',company,finance_book)
        KQma312 = tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'1311%%',company,finance_book)
        KQma313 = tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'333%%',company,finance_book)
        KQma314 = tinh_Co_Cua_Yearly_If_Pos(nam,'334%%',company,finance_book)
        KQma315 = tinh_Co_Cua_Yearly_Finance_Book(nam,'3351%%',company,finance_book)
        KQma316 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'33621%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'33631%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'33681%%',company,finance_book))
        KQma317 = tinh_Co_Cua_Yearly_If_Pos(nam,'337%%',company,finance_book)
        KQma318 = tinh_Co_Cua_Yearly_If_Pos(nam,'33871%%',company,finance_book)
        KQma319 = (tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'3381%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'3382%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'3383%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'3384%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'33851%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'3386%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'33881%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'1381%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'13851%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'13881%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'3441%%',company,finance_book))
        KQma320 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'34111%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'34121%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'343111%%',company,finance_book))
        KQma321 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'35211%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'35221%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'35231%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'35241%%',company,finance_book))
        KQma322 = tinh_Co_Cua_Yearly_Finance_Book(nam,'353%%',company,finance_book)
        KQma323 = tinh_Co_Cua_Yearly_Finance_Book(nam,'357%%',company,finance_book)
        KQma324 = tinh_Co_Cua_Yearly_If_Pos(nam,'171%%',company,finance_book)
        KQma310 =  KQma311 + KQma312 + KQma313 + KQma314 + KQma315 + KQma316 + KQma317 + KQma318 + KQma319 + KQma320 + KQma321 + KQma322 + KQma323 + KQma324

        KQma331 = tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'3312%%',company,finance_book)
        KQma332 = tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'1312%%',company,finance_book)
        KQma333 = tinh_Co_Cua_Yearly_Finance_Book(nam,'3352%%',company,finance_book)
        KQma334 = tinh_Co_Cua_Yearly_Finance_Book(nam,'3361%%',company,finance_book)
        KQma335 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'33622%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'33632%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_Finance_Book(nam,'33682%%',company,finance_book))
        KQma336 = tinh_Co_Cua_Yearly_If_Pos(nam,'33872%%',company,finance_book)
        KQma337 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'3442%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'33852%%',company,finance_book) 
                            + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'33882%%',company,finance_book))
        KQma338 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'34112%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'34122%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'343112%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'34312%%',company,finance_book)  
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'34313%%',company,finance_book))
        KQma339 = tinh_Co_Cua_Yearly_Finance_Book(nam,'3432%%',company,finance_book)
        KQma340 = tinh_Co_Cua_Yearly_Finance_Book(nam,'411122%%',company,finance_book)
        KQma341 = tinh_Co_Cua_Yearly_Finance_Book(nam,'347%%',company,finance_book)
        KQma342 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'35212%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'35222%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'35232%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'35242%%',company,finance_book))	
        KQma343 = tinh_Co_Cua_Yearly_Finance_Book(nam,'356%%',company,finance_book)
        KQma330 =  KQma331 + KQma332 + KQma333 + KQma334 + KQma335 + KQma336 + KQma337 + KQma338 + KQma339 + KQma340 + KQma341 + KQma342 + KQma343



        KQma411a = tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'41111%%',company,finance_book)
        KQma411b =tinh_Co_Cua_Yearly_Finance_Book(nam,'411121%%',company,finance_book)
        KQma411 = KQma411a + KQma411b

        KQma412 = tinh_Co_Cua_Yearly_Finance_Book(nam,'4112%%',company,finance_book)
        KQma413 = tinh_Co_Cua_Yearly_Finance_Book(nam,'4113%%',company,finance_book)
        KQma414 = tinh_Co_Cua_Yearly_Finance_Book(nam,'4118%%',company,finance_book)
        KQma415 = tinh_Co_Cua_Yearly_Finance_Book(nam,'419%%',company,finance_book)
        KQma416 = tinh_Co_Cua_Yearly_Finance_Book(nam,'412%%',company,finance_book)
        KQma417 = tinh_Co_Cua_Yearly_Finance_Book(nam,'413%%',company,finance_book)
        KQma418 = tinh_Co_Cua_Yearly_Finance_Book(nam,'414%%',company,finance_book)
        KQma419 = tinh_Co_Cua_Yearly_Finance_Book(nam,'417%%',company,finance_book)
        KQma420 = tinh_Co_Cua_Yearly_Finance_Book(nam,'418%%',company,finance_book)

        KQma421a = tinh_Co_Cua_Yearly_Finance_Book(nam,'4211%%',company,finance_book)
        KQma421b = tinh_Co_Cua_Yearly_Finance_Book(nam,'4212%%',company,finance_book)
        KQma421 =  KQma421a + KQma421b

        KQma422 =tinh_Co_Cua_Yearly_Finance_Book(nam,'441%%',company,finance_book)
        KQma410 =  KQma411 + KQma412 + KQma413 + KQma414 + KQma415 + KQma416 + KQma417 + KQma418 + KQma419 + KQma420 + KQma421 + KQma422


        KQma431 = (tinh_Co_Cua_Yearly_Finance_Book(nam,'461%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book(nam,'161%%',company,finance_book))
        KQma432 = tinh_Co_Cua_Yearly_Finance_Book(nam,'466%%',company,finance_book)
        KQma430 =  KQma431 + KQma432

        KQma300 =  KQma310 + KQma330
        KQma400 =  KQma410 + KQma430
        KQma440 =  KQma300 + KQma400

        if maso == '100':
            return KQma100
        
        elif maso == '110':
            return KQma110

        elif maso == '111':
            return KQma111
        elif maso == '112':
            return KQma112
        elif maso == '120':
            return KQma120
        elif maso == '121':
            return KQma121
        elif maso == '122':	
            return KQma122
        elif maso == '123':
            return KQma123

        elif maso == '130':
            return KQma130
        elif maso == '131':
            return KQma131
        elif maso == '132':
            return KQma132
        elif maso == '133':
            return  KQma133
        elif maso == '134':
            return KQma134
        elif maso == '135':
            return KQma135
        elif maso == '136':
            return KQma136
        elif maso == '137':
            return KQma137
        elif maso == '139':
            return KQma139
        elif maso == '140':
            return KQma140
        elif maso == '141':
            return KQma141   
        elif maso == '149':
            return KQma149
        elif maso == '150':
            return KQma150
        elif maso == '151':
            return KQma151
        elif maso == '152':
            return KQma152 
        elif maso == '153':
            return KQma153
        elif maso == '154':
            return KQma154
        elif maso == '155':
            return KQma155
        elif maso == '200':
            return KQma200
        elif maso == '210':
            return KQma210
        elif maso == '211':
            return KQma211
        elif maso == '212':
            return KQma212
        elif maso == '213':
            return KQma213
        elif maso == '214':
            return KQma214
        elif maso == '215':
            return KQma215
        elif maso == '216':
            return KQma216
        elif maso == '219':
            return KQma219
        elif maso == '220':
            return KQma220
        elif maso == '221':
            return KQma221
        elif maso == '222':
            return KQma222
        elif maso == '223':
            return KQma223
        elif maso == '224':
            return KQma224
        elif maso == '225':
            return KQma225
        elif maso == '226':
            return KQma226

        elif maso == '227':
            return KQma227
        elif maso == '228':
            return KQma228
        elif maso == '229':
            return KQma229
        elif maso == '230':
            return KQma230
        elif maso == '231':
            return KQma231
        elif maso == '232':
            return KQma232
        elif maso == '240':
            return KQma240
        elif maso == '241':
            return KQma241 
        elif maso == '242':
            return KQma242
        elif maso == '250':
            return KQma250

        elif maso == '251':
            return KQma251
        elif maso == '252':
            return KQma252
        elif maso == '253':
            return KQma253
        elif maso == '254':
            return KQma254
        elif maso == '255':
            return KQma255
        elif maso == '260':
            return KQma260
        elif maso == '261':
            return KQma261
        elif maso == '262':
            return KQma262
        elif maso == '263':
            return KQma263
        elif maso == '268':
            return KQma268
        elif maso == '270':
            return KQma270
            
        elif maso == '300':
            return KQma300
        elif maso == '310':
            return KQma310
       
        elif maso == '311':
            return KQma311
        elif maso == '312':
            return KQma312
        elif maso == '313':
            return KQma313
        elif maso == '314':
            return KQma314
        elif maso == '315':
            return KQma315
        elif maso == '316':
            return KQma316
        elif maso == '317':
            return KQma317
        elif maso == '318':
            return KQma318
        elif maso == '319':
            return KQma319
        elif maso == '320':
            return KQma320
        elif maso == '321':
            return KQma321
        elif maso == '322':
            return KQma322
        elif maso == '323':
            return KQma323
        elif maso == '324':
            return KQma324
        elif maso == '330':
            return KQma330
       		
        elif maso == '331':
            return KQma331
        elif maso == '332':
            return KQma332
        elif maso == '333':
            return KQma333
        elif maso == '334':
            return KQma334
        elif maso == '335':
            return KQma335
        elif maso == '336':
            return KQma336
        elif maso == '337':
            return KQma337
        elif maso == '338':
            return KQma338
        elif maso == '339':
            return KQma339
        elif maso == '340':
            return KQma340
        elif maso == '341':
            return KQma341
        elif maso == '342':
            return KQma342
        elif maso == '343':
            return KQma343
        elif maso == '400':
            return KQma400
        elif maso == '410':
            return KQma410
        elif maso == '411':
            return KQma411
        elif maso == '411a':
            return KQma411a
        elif maso == '411b':
            return KQma411b
        elif maso == '412':
            return KQma412
        elif maso == '413':
            return KQma413
        elif maso == '414':
            return KQma414
        elif maso == '415':
            return KQma415
        elif maso == '416':
            return KQma416
        elif maso == '417':
            return KQma417
        elif maso == '418':
            return KQma418
        elif maso == '419':
            return KQma419
        elif maso == '420':
            return KQma420
        elif maso == '421':
            return KQma421
        elif maso == '421a':
            return KQma421a
        elif maso == '421b':
            return KQma421b
        elif maso == '422':
            return KQma422
        elif maso == '430':
            return KQma430
        elif maso == '431':
            return KQma431
        elif maso == '432':
            return KQma432
        elif maso == '440':
            return  KQma440
    else:
        return 0
        # if maso == '110':
        #     if Vitri == 0:
        #         return      (tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'111%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'112%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'113%%',company,finance_book) 
        #                     + (tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12811%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12881%%',company,finance_book)))
        #     else:
        #         return (tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'111%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'112%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'113%%',company,finance_book) 
        #                     + (tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12811%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12881%%',company,finance_book)))

        # elif maso == '111':
        #     if Vitri == 0:
        #          return ((tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'111%%',company,finance_book)) 
        #                 + (tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'112%%',company,finance_book)) 
        #                 + (tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'113%%',company,finance_book)))
        #     else:
        #         return ((tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'111%%',company,finance_book)) 
        #                 + (tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'112%%',company,finance_book)) 
        #                 + (tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'113%%',company,finance_book)))

        # elif maso == '112':
        #     if Vitri == 0:
        #          return (tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12811%%',company,finance_book) 
        #             + tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12881%%',company,finance_book))
        #     else:
        #         return (tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12811%%',company,finance_book) 
        #                 + tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12881%%',company,finance_book))

        # elif maso == '123':
        #     if Vitri == 0:
        #         return      (tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12812%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12821%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Opening(nam,'12882%%',company,finance_book))
        #     else:
        #         return (tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12812%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12821%%',company,finance_book) 
        #                     + tinh_No_Yearly_Finance_Book_PostingDate_Mid(nam,'12882%%',company,finance_book))
        # else:
        #     return 0


        
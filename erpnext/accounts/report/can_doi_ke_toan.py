# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from calendar import c
from cgi import test
from cmath import e
import functools
import math
import re
from unicodedata import name
from braintree import TransactionSearch

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, flt, formatdate, get_first_day, getdate, list_to_str
from html2text import element_style
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
        #   period.to_date_fiscal_year = get_fiscal_year(period.to_date, company=company)[0]
        #   period.from_date_fiscal_year_start_date = get_fiscal_year(period.from_date, company=company)[1]

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
    if a+b > 0:
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
def tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,account,company,finance_book):
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

def tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,account,company,finance_book):
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

def tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,account,company,finance_book):
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

def tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,account,company,finance_book):
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
def tinh_No_Cua_Yearly_If_Pos_PostingDate_Opening(nam,account,company,finance_book):
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
def tinh_No_Cua_Yearly_If_Pos_PostingDate_Mid(nam,account,company,finance_book):
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

def tinh_Co_Cua_Yearly_If_Pos_PostingDate_Opening(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    a = frappe.db.sql("""
            SELECT 
		posting_date,fiscal_year,(SUM(credit)-SUM(debit)) AS total
		from `tabGL Entry`
		where
			company=%(company)s
			AND (account LIKE %(account)s
				)
			and is_cancelled = 0
            and fiscal_year<=%(namt)s
			GROUP BY ACCOUNT
            having total>0
            """,test,as_dict=True)
    b = frappe.db.sql("""
    SELECT 
		posting_date,fiscal_year,(SUM(credit)-SUM(debit)) AS total
		from `tabGL Entry`
		where
			company=%(company)s
			AND (account LIKE %(account)s
				)
            and finance_book=%(finance_book)s
			and is_cancelled = 0
			and fiscal_year<=%(namt)s
			GROUP BY ACCOUNT
            having total>0
            """,test,as_dict=True)
    kq=0
    for i in a:
        if(int(i.fiscal_year)<nam.from_date.year or i.posting_date<=nam.to_date):
            kq+=i.total
    for i in b:
        if(int(i.fiscal_year)<nam.from_date.year or i.posting_date<=nam.to_date):
            kq+=i.total
    return kq

def tinh_Co_Cua_Yearly_If_Pos_PostingDate_Mid(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    a = frappe.db.sql("""
            SELECT 
		posting_date,fiscal_year,(SUM(credit)-SUM(debit)) AS total
		from `tabGL Entry`
		where
			company=%(company)s
			AND (account LIKE %(account)s
				)
			and is_cancelled = 0
            and fiscal_year<=%(namt)s
			GROUP BY ACCOUNT
            having total>0
            """,test,as_dict=True)
    b = frappe.db.sql("""
    SELECT 
		posting_date,fiscal_year,(SUM(credit)-SUM(debit)) AS total
		from `tabGL Entry`
		where
			company=%(company)s
			AND (account LIKE %(account)s
				)
            and finance_book=%(finance_book)s
			and is_cancelled = 0
			and fiscal_year<=%(namt)s
			GROUP BY ACCOUNT
            having total>0
            """,test,as_dict=True)
    kq=0
    for i in a:
        if(int(i.fiscal_year)==nam.from_date.year and i.posting_date>=nam.from_date and i.posting_date<=nam.to_date):
            kq+=i.total
    for i in b:
        if(int(i.fiscal_year)==nam.from_date.year and i.posting_date>=nam.from_date and i.posting_date<=nam.to_date):
            kq+=i.total
    return kq
  

## Điều kiện Nợ - Có luôn âm có finance_book
def tinh_No_Cua_Yearly_If_Nega_PostingDate_Opening(nam,account,company,finance_book):
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
def tinh_No_Cua_Yearly_If_Nega_PostingDate_Mid(nam,account,company,finance_book):
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
def tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    a = frappe.db.sql("""
            select posting_date,fiscal_year,(sum(debit)-sum(credit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.fiscal_year<= %(namt)s
                group by Account having total > 0""",test,as_dict=True)  
    ma313 = 0
    for party in a :
        if(int(party.fiscal_year)<nam.from_date.year or party.posting_date<=nam.to_date):
            ma313+=party.total  
    return ma313
def tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    a = frappe.db.sql("""
            select posting_date,fiscal_year,(sum(debit)-sum(credit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.fiscal_year<= %(namt)s
                group by Account having total > 0""",test,as_dict=True)  
    ma313 = 0
    for party in a :
        if(int(party.fiscal_year)==nam.from_date.year and party.posting_date<=nam.to_date and party.posting_date>=nam.from_date):
            ma313+=party.total  
    return ma313

def tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    a = frappe.db.sql("""
            select fiscal_year,posting_date,(sum(credit)-sum(debit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.fiscal_year<=%(namt)s
                group by Account having total > 0""",test,as_dict=True)  
    ma313 = 0
    for party in a :
        if(int(party.fiscal_year)<nam.from_date.year or party.posting_date<=nam.to_date):
            ma313+=party.total  
    return ma313
def tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    a = frappe.db.sql("""
            select fiscal_year,posting_date,(sum(credit)-sum(debit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.fiscal_year<=%(namt)s
                group by Account having total > 0""",test,as_dict=True)  
    ma313 = 0
    for party in a :
        if(int(party.fiscal_year)==nam.from_date.year and party.posting_date<=nam.to_date and party.posting_date>=nam.from_date):
            ma313+=party.total  
    return ma313


def tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,account,company,finance_book):
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
def tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,account,company,finance_book):
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
def tinh_No_Yearly_Finance_Book_Party_Pos_Opening(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    list = frappe.db.sql("""
            select posting_date,fiscal_year,(sum(debit)-sum(credit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and is_cancelled = 0
                and (gle.fiscal_year between 2000 AND %(namt)s or ifnull(is_opening, 'No') = 'Yes')
                group by account,party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
            select posting_date,fiscal_year,(sum(debit)-sum(credit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and is_cancelled = 0
                and (gle.fiscal_year between 2000 AND %(namt)s or ifnull(is_opening, 'No') = 'Yes')
                group by account,party having total > 0""",test,as_dict=True)  
    Prt = 0

    for party in list :
        if(int(party.fiscal_year)<nam.from_date.year or party.posting_date<=nam.to_date):
            Prt+=party.total 
    for party in a :
        if(int(party.fiscal_year)<nam.from_date.year or party.posting_date<=nam.to_date):
            Prt+=party.total   
    return Prt
def tinh_No_Yearly_Finance_Book_Party_Pos_Mid(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    list = frappe.db.sql("""
            select posting_date,fiscal_year,(sum(debit)-sum(credit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and is_cancelled = 0
                and (gle.fiscal_year between 2000 AND %(namt)s or ifnull(is_opening, 'No') = 'Yes')
                group by account,party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
            select posting_date,fiscal_year,(sum(debit)-sum(credit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and is_cancelled = 0
                and (gle.fiscal_year between 2000 AND %(namt)s or ifnull(is_opening, 'No') = 'Yes')
                group by account,party having total > 0""",test,as_dict=True)  
    Prt = 0
    for party in list :
        if(int(party.fiscal_year)==nam.from_date.year and party.posting_date>=nam.from_date and party.posting_date<=nam.to_date ):
            Prt+=party.total  
    for party in a :
        if(int(party.fiscal_year)==nam.from_date.year and party.posting_date>=nam.from_date and party.posting_date<=nam.to_date ):
            Prt+=party.total   
    return Prt

def tinh_Co_Yearly_Finance_Book_Party_Pos_Opening(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    list = frappe.db.sql("""
            select fiscal_year,posting_date,(sum(credit)-sum(debit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and is_cancelled = 0
                and gle.fiscal_year<= %(namt)s
                group by account,party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
            select fiscal_year,posting_date,(sum(credit)-sum(debit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and is_cancelled = 0
                and gle.fiscal_year<= %(namt)s
                group by account,party having total > 0""",test,as_dict=True) 
    Prt = 0

    for party in list :
        if(int(party.fiscal_year)<nam.from_date.year or party.posting_date<=nam.to_date):
            Prt+=party.total 
    for party in a :
        if(int(party.fiscal_year)<nam.from_date.year or party.posting_date<=nam.to_date):
            Prt+=party.total   
    return Prt
def tinh_Co_Yearly_Finance_Book_Party_Pos_Mid(nam,account,company,finance_book):
    test={
            "from_date":nam.from_date,
            "to_date":nam.to_date,
            "account":account,
            "company":company,
            "finance_book":finance_book,
            "namt":nam.from_date.year
    }
    list = frappe.db.sql("""
            select fiscal_year,posting_date,(sum(credit)-sum(debit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and gle.finance_book = %(finance_book)s
                and is_cancelled = 0
                and gle.fiscal_year<= %(namt)s
                group by account,party having total > 0""",test,as_dict=True)
    a = frappe.db.sql("""
            select fiscal_year,posting_date,(sum(credit)-sum(debit)) total
            from `tabGL Entry` as gle
            where gle.account LIKE %(account)s
                and gle.company = %(company)s
                and is_cancelled = 0
                and gle.fiscal_year<= %(namt)s
                group by account,party having total > 0""",test,as_dict=True) 
    Prt = 0

    for party in list :
        if(int(party.fiscal_year)==nam.from_date.year and party.posting_date<=nam.to_date and party.posting_date>=nam.from_date):
            Prt+=party.total 
    for party in a :
        if(int(party.fiscal_year)==nam.from_date.year and party.posting_date<=nam.to_date and party.posting_date>=nam.from_date):
            Prt+=party.total   
    return Prt

def get_accounts():
    return frappe.db.sql("""
        select taisan, maso
        from `tabBangCanDoiKeToan` order by maso
        """,as_dict=True)

def get_columns(periodicity, period_list, accumulated_values=1, company=True):
    columns = [{
            "fieldname": "taisan",
            "label": _("Tài Sản"),
            "fieldtype": "Data",
            "options": "BangCanDoiKeToan",
            "width": 400
    },{
            "fieldname": "maso",
            "label": "Mã Số",
            "fieldtype": "Link",
            "options": "BangCanDoiKeToan",
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

def tinhMa111(nam,company,finance_book):
        return ((tinh_No_Cua_Yearly_Finance_Book(nam,'111%%',company,finance_book)) 
                        + (tinh_No_Cua_Yearly_Finance_Book(nam,'112%%',company,finance_book)) 
                        + (tinh_No_Cua_Yearly_Finance_Book(nam,'113%%',company,finance_book)))
def tinhMa112(nam, company,finance_book):
        return (tinh_No_Cua_Yearly_Finance_Book(nam,'12811%%',company,finance_book) 
                        + tinh_No_Cua_Yearly_Finance_Book(nam,'12881%%',company,finance_book))
def tinhMa121(nam, company,finance_book):
        return tinh_No_Cua_Yearly_Finance_Book(nam,'121%%',company,finance_book)
def tinhMa122(nam, company,finance_book):
        return tinh_Co_Cua_Yearly_If_Nega(nam,'2291%%',company,finance_book)
def tinhMa123(nam, company,finance_book):
        return (tinh_No_Cua_Yearly_Finance_Book(nam,'12812%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book(nam,'12821%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book(nam,'12882%%',company,finance_book))
def tinhMa131(nam, company,finance_book):
        return tinh_No_Yearly_Finance_Book_Party_Pos(nam,'1311%',company,finance_book)
def tinhMa132(nam, company,finance_book):
        return tinh_No_Yearly_Finance_Book_Party_Pos(nam,'3311%%',company,finance_book)
def tinhMa133(nam, company,finance_book):
        return (tinh_No_Cua_Yearly_Finance_Book(nam,'13621%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book(nam,'13631%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book(nam,'13681%%',company,finance_book))
def tinhMa134(nam, company,finance_book):
        return tinh_No_Cua_Yearly_If_Pos(nam,'337%%',company,finance_book)
def tinhMa135(nam, company,finance_book):
        return tinh_No_Cua_Yearly_Finance_Book(nam,'12831%%',company,finance_book)

def tinhMa136(nam, company,finance_book):
        return (tinh_No_Cua_Yearly_Finance_Book(nam,'1411%%',company,finance_book)
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
def tinhMa137(nam, company,finance_book):
        return tinh_Co_Cua_Yearly_If_Nega(nam,'22931%%',company,finance_book)
def tinhMa139(nam, company,finance_book):
        return tinh_No_Cua_Yearly_If_Pos(nam,'1381%%',company,finance_book)
def tinhMa141(nam, company,finance_book):
        return (tinh_No_Cua_Yearly_Finance_Book(nam,'151%%',company,finance_book) 
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
def tinhMa149(nam, company,finance_book):
        return tinh_No_Cua_Yearly_If_Nega(nam,'22941%%',company,finance_book)
def tinhMa151(nam, company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'2421%%',company,finance_book)
def tinhMa152(nam, company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'133%%',company,finance_book) 
def tinhMa153(nam, company,finance_book):
    return tinh_No_Cua_Yearly_If_Pos_ma153(nam,'333%%',company,finance_book)  
def tinhMa154(nam, company,finance_book):
    return tinh_No_Cua_Yearly_If_Pos(nam,'171%%',company,finance_book)
def tinhMa155(nam, company,finance_book):  
    return tinh_No_Cua_Yearly_Finance_Book(nam,'22881%%',company,finance_book)
def tinhMa211 (nam,company,finance_book):
        return tinh_No_Yearly_Finance_Book_Party_Pos(nam,'1312%%',company,finance_book)
def tinhMa212 (nam,company,finance_book):
    return tinh_No_Yearly_Finance_Book_Party_Pos(nam,'3312%%',company,finance_book)
def tinhMa213 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'1361%%',company,finance_book)
def tinhMa214 (nam,company,finance_book):
    return (tinh_No_Cua_Yearly_Finance_Book(nam,'13622%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book(nam,'13632%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book(nam,'13682%%',company,finance_book))
def tinhMa215 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'12832%%',company,finance_book)
def tinhMa216 (nam,company,finance_book):
    return (tinh_No_Cua_Yearly_If_Pos_ma313(nam,'13852%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'13882%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'1412%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'2442%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33852%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33872%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313(nam,'33882%%',company,finance_book))
def tinhMa219 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_If_Nega(nam,'22932%%',company,finance_book) 
def tinhMa222 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'211%%',company,finance_book)
def tinhMa223 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Nega(nam,'2141%%',company,finance_book)
def tinhMa225 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'212%%',company,finance_book)
def tinhMa226 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Nega(nam,'2142%%',company,finance_book)
def tinhMa228 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'213%%',company,finance_book)
def tinhMa229 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Nega(nam,'2143%%',company,finance_book)
def tinhMa231 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'217%%',company,finance_book)
def tinhMa232 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Nega(nam,'2147%%',company,finance_book)
def tinhMa241 (nam,company,finance_book):
    return (tinh_No_Cua_Yearly_Finance_Book(nam,'1542%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'22942%%',company,finance_book))
def tinhMa242 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'241%%',company,finance_book)
def tinhMa251 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'221%%',company,finance_book)
def tinhMa252 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'222%%',company,finance_book)
def tinhMa253 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'2281%%',company,finance_book)
def tinhMa254 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Nega(nam,'2292%%',company,finance_book)
def tinhMa255 (nam,company,finance_book):
    return (tinh_No_Cua_Yearly_Finance_Book(nam,'12813%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book(nam,'12822%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book(nam,'12883%%',company,finance_book))
def tinhMa261 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'2422%%',company,finance_book)
def tinhMa262 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'243%%',company,finance_book)
def tinhMa263 (nam,company,finance_book):
    return (tinh_No_Cua_Yearly_Finance_Book(nam,'22943%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book(nam,'15342%%',company,finance_book))
def tinhMa268 (nam,company,finance_book):
    return tinh_No_Cua_Yearly_Finance_Book(nam,'22882%%',company,finance_book)
def tinhMa311 (nam,company,finance_book):
    return tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'3311%%',company,finance_book)
def tinhMa312 (nam,company,finance_book):
    return tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'1311%%',company,finance_book)
def tinhMa313 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'333%%',company,finance_book)
def tinhMa314 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Pos(nam,'334%%',company,finance_book)
def tinhMa315 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'3351%%',company,finance_book)
def tinhMa316 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'33621%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'33631%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'33681%%',company,finance_book))
def tinhMa317 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Pos(nam,'337%%',company,finance_book)
def tinhMa318 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Pos(nam,'33871%%',company,finance_book)
def tinhMa319 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'3381%%',company,finance_book) 
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
def tinhMa320 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'34111%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'34121%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'343111%%',company,finance_book))
def tinhMa321 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'35211%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'35221%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'35231%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'35241%%',company,finance_book))
def tinhMa322 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'353%%',company,finance_book)
def tinhMa323 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'357%%',company,finance_book)
def tinhMa324 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Pos(nam,'171%%',company,finance_book)
def tinhMa331 (nam,company,finance_book):
    return tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'3312%%',company,finance_book)
def tinhMa332 (nam,company,finance_book):
    return tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'1312%%',company,finance_book)
def tinhMa333 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'3352%%',company,finance_book)
def tinhMa334 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'3361%%',company,finance_book)
def tinhMa335 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'33622%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'33632%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book(nam,'33682%%',company,finance_book))
def tinhMa336 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_If_Pos(nam,'33872%%',company,finance_book)
def tinhMa337 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'3442%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'33852%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_If_Pos_ma313(nam,'33882%%',company,finance_book))
def tinhMa338 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'34112%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'34122%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'343112%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'34312%%',company,finance_book)  
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'34313%%',company,finance_book))
def tinhMa339 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'3432%%',company,finance_book)
def tinhMa340 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'411122%%',company,finance_book)
def tinhMa341 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'347%%',company,finance_book)
def tinhMa342 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'35212%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'35222%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'35232%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'35242%%',company,finance_book))  
def tinhMa343 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'356%%',company,finance_book)
def tinhMa411a (nam,company,finance_book):
    return tinh_Co_Yearly_Finance_Book_Party_Pos(nam,'41111%%',company,finance_book)
def tinhMa411b (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'411121%%',company,finance_book)
def tinhMa412 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'4112%%',company,finance_book)
def tinhMa413 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'4113%%',company,finance_book)
def tinhMa414 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'4118%%',company,finance_book)
def tinhMa415 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'419%%',company,finance_book)
def tinhMa416 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'412%%',company,finance_book)
def tinhMa417 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'413%%',company,finance_book)
def tinhMa418 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'414%%',company,finance_book)
def tinhMa419 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'417%%',company,finance_book)
def tinhMa420 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'418%%',company,finance_book)
def tinhMa421a (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'4211%%',company,finance_book)
def tinhMa421b (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'4212%%',company,finance_book)
def tinhMa422 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'441%%',company,finance_book)
def tinhMa431 (nam,company,finance_book):
    return (tinh_Co_Cua_Yearly_Finance_Book(nam,'461%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book(nam,'161%%',company,finance_book))
def tinhMa432 (nam,company,finance_book):
    return tinh_Co_Cua_Yearly_Finance_Book(nam,'466%%',company,finance_book)
def get_giatri(nam,maso,periodicity,company,finance_book):
    if periodicity== "Yearly":
        nam = nam.label
        if maso == '100':
            return (tinhMa111(nam,company,finance_book)+tinhMa112(nam,company,finance_book)+
            tinhMa122(nam,company,finance_book)+tinhMa121(nam,company,finance_book)
                                                +tinhMa123(nam,company,finance_book)+
            tinhMa131(nam,company,finance_book)+tinhMa132(nam,company,finance_book)
                +tinhMa133(nam,company,finance_book)+tinhMa134(nam,company,finance_book)
                +tinhMa135(nam,company,finance_book)+tinhMa136(nam,company,finance_book)
                +tinhMa137(nam,company,finance_book)+tinhMa139(nam,company,finance_book)+
            tinhMa141(nam,company,finance_book)+tinhMa149(nam,company,finance_book)+
            tinhMa151(nam,company,finance_book)+tinhMa152(nam,company,finance_book)
                +tinhMa153(nam,company,finance_book)+tinhMa154(nam,company,finance_book)
                +tinhMa155(nam,company,finance_book))

        elif maso == '110':
            return tinhMa111(nam,company,finance_book)+tinhMa112(nam,company,finance_book)
        elif maso == '111':
            return tinhMa111(nam,company,finance_book)
        elif maso == '112':
            return tinhMa112(nam,company,finance_book)
        elif maso == '120':
            return (tinhMa122(nam,company,finance_book)+tinhMa121(nam,company,finance_book)
                    +tinhMa123(nam,company,finance_book))
        elif maso == '121':
            return tinhMa121(nam,company,finance_book)
        elif maso == '122': 
            return tinhMa122(nam,company,finance_book)
        elif maso == '123':
            return tinhMa123(nam,company,finance_book)

        elif maso == '130':
            return (tinhMa131(nam,company,finance_book)+tinhMa132(nam,company,finance_book)
            +tinhMa133(nam,company,finance_book)+tinhMa134(nam,company,finance_book)
            +tinhMa135(nam,company,finance_book)+tinhMa136(nam,company,finance_book)
            +tinhMa137(nam,company,finance_book)+tinhMa139(nam,company,finance_book))
        elif maso == '131':
            return tinhMa131(nam,company,finance_book)
        elif maso == '132':
            return tinhMa132(nam,company,finance_book)
        elif maso == '133':
            return  tinhMa133(nam,company,finance_book)
        elif maso == '134':
            return tinhMa134(nam,company,finance_book)
        elif maso == '135':
            return tinhMa135(nam,company,finance_book)
        elif maso == '136':
            return tinhMa136(nam,company,finance_book)
        elif maso == '137':
            return tinhMa137(nam,company,finance_book)
        elif maso == '139':
            return tinhMa139(nam,company,finance_book)
        elif maso == '140':
            return tinhMa141(nam,company,finance_book)+tinhMa149(nam,company,finance_book)
        elif maso == '141':
            return tinhMa141(nam,company,finance_book)   
        elif maso == '149':
            return tinhMa149(nam,company,finance_book)
        elif maso == '150':
            return (tinhMa151(nam,company,finance_book)+tinhMa152(nam,company,finance_book)
            +tinhMa153(nam,company,finance_book)+tinhMa154(nam,company,finance_book)
            +tinhMa155(nam,company,finance_book))
        elif maso == '151':
            return tinhMa151(nam,company,finance_book)
        elif maso == '152':
            return tinhMa152(nam,company,finance_book) 
        elif maso == '153':
            return tinhMa153(nam,company,finance_book)
        elif maso == '154':
            return tinhMa154(nam,company,finance_book)
        elif maso == '155':
            return tinhMa155(nam,company,finance_book)
        elif maso == '200':
            return (tinhMa211(nam,company,finance_book)+tinhMa212(nam,company,finance_book)
                +tinhMa213(nam,company,finance_book)+tinhMa214(nam,company,finance_book)
                +tinhMa215(nam,company,finance_book)+tinhMa216(nam,company,finance_book)
                +tinhMa219(nam,company,finance_book)+
                    tinhMa222(nam,company,finance_book)+tinhMa223(nam,company,finance_book)
                +tinhMa225(nam,company,finance_book)+tinhMa226(nam,company,finance_book)
                +tinhMa229(nam,company,finance_book)+tinhMa228(nam,company,finance_book)+
                    tinhMa231(nam,company,finance_book)+tinhMa232(nam,company,finance_book)+
                    tinhMa241(nam,company,finance_book)+tinhMa242(nam,company,finance_book)+
                    tinhMa251(nam,company,finance_book)+tinhMa252(nam,company,finance_book)
                +tinhMa253(nam,company,finance_book)+tinhMa254(nam,company,finance_book)
                +tinhMa255(nam,company,finance_book)+
                    tinhMa261(nam,company,finance_book)+tinhMa262(nam,company,finance_book)
                +tinhMa263(nam,company,finance_book)+tinhMa268(nam,company,finance_book))
        elif maso == '210':
            return (tinhMa211(nam,company,finance_book)+tinhMa212(nam,company,finance_book)
            +tinhMa213(nam,company,finance_book)+tinhMa214(nam,company,finance_book)
            +tinhMa215(nam,company,finance_book)+tinhMa216(nam,company,finance_book)
            +tinhMa219(nam,company,finance_book))
        elif maso == '211':
            return tinhMa211(nam,company,finance_book)
        elif maso == '212':
            return tinhMa212(nam,company,finance_book)
        elif maso == '213':
            return tinhMa213(nam,company,finance_book)
        elif maso == '214':
            return tinhMa214(nam,company,finance_book)
        elif maso == '215':
            return tinhMa215(nam,company,finance_book)
        elif maso == '216':
            return tinhMa216(nam,company,finance_book)
        elif maso == '219':
            return tinhMa219(nam,company,finance_book)
        elif maso == '220':
            return (tinhMa222(nam,company,finance_book)+tinhMa223(nam,company,finance_book)
            +tinhMa225(nam,company,finance_book)+tinhMa226(nam,company,finance_book)
            +tinhMa229(nam,company,finance_book)+tinhMa228(nam,company,finance_book))

        elif maso == '221':
            return tinhMa222(nam,company,finance_book)+tinhMa223(nam,company,finance_book)
        elif maso == '222':
            return tinhMa222(nam,company,finance_book)
        elif maso == '223':
            return tinhMa223(nam,company,finance_book)
        elif maso == '224':
            return tinhMa225(nam,company,finance_book)+tinhMa226(nam,company,finance_book)
        elif maso == '225':
            return tinhMa225(nam,company,finance_book)
        elif maso == '226':
            return tinhMa226(nam,company,finance_book)

        elif maso == '227':
            return tinhMa229(nam,company,finance_book)+tinhMa228(nam,company,finance_book)
        elif maso == '228':
            return tinhMa228(nam,company,finance_book)
        elif maso == '229':
            return tinhMa229(nam,company,finance_book)
        elif maso == '230':
            return tinhMa231(nam,company,finance_book)+tinhMa232(nam,company,finance_book)
        elif maso == '231':
            return tinhMa231(nam,company,finance_book)
        elif maso == '232':
            return tinhMa232(nam,company,finance_book)
        elif maso == '240':
            return tinhMa241(nam,company,finance_book)+tinhMa242(nam,company,finance_book)
        elif maso == '241':
            return tinhMa241(nam,company,finance_book) 
        elif maso == '242':
            return tinhMa242(nam,company,finance_book)
        elif maso == '250':
            return (
                tinhMa251(nam,company,finance_book)+tinhMa252(nam,company,finance_book)
                +tinhMa253(nam,company,finance_book)+tinhMa254(nam,company,finance_book)
                +tinhMa255(nam,company,finance_book))

        elif maso == '251':
            return tinhMa251(nam,company,finance_book)
        elif maso == '252':
            return tinhMa252(nam,company,finance_book)
        elif maso == '253':
            return tinhMa253(nam,company,finance_book)
        elif maso == '254':
            return tinhMa254(nam,company,finance_book)
        elif maso == '255':
            return tinhMa255(nam,company,finance_book)
        elif maso == '260':
            return (tinhMa261(nam,company,finance_book)+tinhMa262(nam,company,finance_book)
            +tinhMa263(nam,company,finance_book)+tinhMa268(nam,company,finance_book))
        elif maso == '261':
            return tinhMa261(nam,company,finance_book)
        elif maso == '262':
            return tinhMa262(nam,company,finance_book)
        elif maso == '263':
            return tinhMa263(nam,company,finance_book)
        elif maso == '268':
            return tinhMa268(nam,company,finance_book)
        elif maso == '270':
            return (tinhMa111(nam,company,finance_book)+tinhMa112(nam,company,finance_book)+
            tinhMa122(nam,company,finance_book)+tinhMa121(nam,company,finance_book)
                                                +tinhMa123(nam,company,finance_book)+
            tinhMa131(nam,company,finance_book)+tinhMa132(nam,company,finance_book)
                +tinhMa133(nam,company,finance_book)+tinhMa134(nam,company,finance_book)
                +tinhMa135(nam,company,finance_book)+tinhMa136(nam,company,finance_book)
                +tinhMa137(nam,company,finance_book)+tinhMa139(nam,company,finance_book)+
            tinhMa141(nam,company,finance_book)+tinhMa149(nam,company,finance_book)+
            tinhMa151(nam,company,finance_book)+tinhMa152(nam,company,finance_book)
                +tinhMa153(nam,company,finance_book)+tinhMa154(nam,company,finance_book)
                +tinhMa155(nam,company,finance_book)+
                    tinhMa211(nam,company,finance_book)+tinhMa212(nam,company,finance_book)
                +tinhMa213(nam,company,finance_book)+tinhMa214(nam,company,finance_book)
                +tinhMa215(nam,company,finance_book)+tinhMa216(nam,company,finance_book)
                +tinhMa219(nam,company,finance_book)+
                    tinhMa222(nam,company,finance_book)+tinhMa223(nam,company,finance_book)
                +tinhMa225(nam,company,finance_book)+tinhMa226(nam,company,finance_book)
                +tinhMa229(nam,company,finance_book)+tinhMa228(nam,company,finance_book)+
                    tinhMa231(nam,company,finance_book)+tinhMa232(nam,company,finance_book)+
                    tinhMa241(nam,company,finance_book)+tinhMa242(nam,company,finance_book)+
                    tinhMa251(nam,company,finance_book)+tinhMa252(nam,company,finance_book)
                +tinhMa253(nam,company,finance_book)+tinhMa254(nam,company,finance_book)
                +tinhMa255(nam,company,finance_book)+
                    tinhMa261(nam,company,finance_book)+tinhMa262(nam,company,finance_book)
                +tinhMa263(nam,company,finance_book)+tinhMa268(nam,company,finance_book))
            
        elif maso == '300':
            return (tinhMa311(nam,company,finance_book)+tinhMa312(nam,company,finance_book)
            +tinhMa313(nam,company,finance_book)+tinhMa314(nam,company,finance_book)
            +tinhMa315(nam,company,finance_book)+tinhMa316(nam,company,finance_book)
            +tinhMa317(nam,company,finance_book)+tinhMa318(nam,company,finance_book)
            +tinhMa319(nam,company,finance_book)+tinhMa320(nam,company,finance_book)
            +tinhMa321(nam,company,finance_book)+tinhMa322(nam,company,finance_book)
            +tinhMa323(nam,company,finance_book)+tinhMa324(nam,company,finance_book)+
                tinhMa331(nam,company,finance_book)+tinhMa332(nam,company,finance_book)
            +tinhMa333(nam,company,finance_book)+tinhMa334(nam,company,finance_book)
            +tinhMa335(nam,company,finance_book)+tinhMa336(nam,company,finance_book)
            +tinhMa337(nam,company,finance_book)+tinhMa338(nam,company,finance_book)
            +tinhMa339(nam,company,finance_book)+tinhMa340(nam,company,finance_book)
            +tinhMa341(nam,company,finance_book)+tinhMa342(nam,company,finance_book)
            +tinhMa343(nam,company,finance_book))
        elif maso == '310':
            return (tinhMa311(nam,company,finance_book)+tinhMa312(nam,company,finance_book)
            +tinhMa313(nam,company,finance_book)+tinhMa314(nam,company,finance_book)
            +tinhMa315(nam,company,finance_book)+tinhMa316(nam,company,finance_book)
            +tinhMa317(nam,company,finance_book)+tinhMa318(nam,company,finance_book)
            +tinhMa319(nam,company,finance_book)+tinhMa320(nam,company,finance_book)
            +tinhMa321(nam,company,finance_book)+tinhMa322(nam,company,finance_book)
            +tinhMa323(nam,company,finance_book)+tinhMa324(nam,company,finance_book))

        elif maso == '311':
            return tinhMa311(nam,company,finance_book)
        elif maso == '312':
            return tinhMa312(nam,company,finance_book)
        elif maso == '313':
            return tinhMa313(nam,company,finance_book)
        elif maso == '314':
            return tinhMa314(nam,company,finance_book)
        elif maso == '315':
            return tinhMa315(nam,company,finance_book)
        elif maso == '316':
            return tinhMa316(nam,company,finance_book)
        elif maso == '317':
            return tinhMa317(nam,company,finance_book)
        elif maso == '318':
            return tinhMa318(nam,company,finance_book)
        elif maso == '319':
            return tinhMa319(nam,company,finance_book)
        elif maso == '320':
            return tinhMa320(nam,company,finance_book)
        elif maso == '321':
            return tinhMa321(nam,company,finance_book)
        elif maso == '322':
            return tinhMa322(nam,company,finance_book)
        elif maso == '323':
            return tinhMa323(nam,company,finance_book)
        elif maso == '324':
            return tinhMa324(nam,company,finance_book)
        elif maso == '330':
            return (tinhMa331(nam,company,finance_book)+tinhMa332(nam,company,finance_book)
            +tinhMa333(nam,company,finance_book)+tinhMa334(nam,company,finance_book)
            +tinhMa335(nam,company,finance_book)+tinhMa336(nam,company,finance_book)
            +tinhMa337(nam,company,finance_book)+tinhMa338(nam,company,finance_book)
            +tinhMa339(nam,company,finance_book)+tinhMa340(nam,company,finance_book)
            +tinhMa341(nam,company,finance_book)+tinhMa342(nam,company,finance_book)
            +tinhMa343(nam,company,finance_book))
            
        elif maso == '331':
            return tinhMa331(nam,company,finance_book)
        elif maso == '332':
            return tinhMa332(nam,company,finance_book)
        elif maso == '333':
            return tinhMa333(nam,company,finance_book)
        elif maso == '334':
            return tinhMa334(nam,company,finance_book)
        elif maso == '335':
            return tinhMa335(nam,company,finance_book)
        elif maso == '336':
            return tinhMa336(nam,company,finance_book)
        elif maso == '337':
            return tinhMa337(nam,company,finance_book)
        elif maso == '338':
            return tinhMa338(nam,company,finance_book)
        elif maso == '339':
            return tinhMa339(nam,company,finance_book)
        elif maso == '340':
            return tinhMa340(nam,company,finance_book)
        elif maso == '341':
            return tinhMa341(nam,company,finance_book)
        elif maso == '342':
            return tinhMa342(nam,company,finance_book)
        elif maso == '343':
            return tinhMa343(nam,company,finance_book)
        elif maso == '400':
            return (tinhMa411a(nam,company,finance_book)+tinhMa411b(nam,company,finance_book)
            +tinhMa412(nam,company,finance_book)+tinhMa413(nam,company,finance_book)
            +tinhMa414(nam,company,finance_book)+tinhMa415(nam,company,finance_book)
            +tinhMa416(nam,company,finance_book)+tinhMa417(nam,company,finance_book)
            +tinhMa418(nam,company,finance_book)+tinhMa419(nam,company,finance_book)
            +tinhMa420(nam,company,finance_book)+tinhMa421a(nam,company,finance_book)
            +tinhMa421b(nam,company,finance_book)+tinhMa422(nam,company,finance_book)+
                tinhMa431(nam,company,finance_book)+tinhMa432(nam,company,finance_book))

        elif maso == '410':
            return (tinhMa411a(nam,company,finance_book)+tinhMa411b(nam,company,finance_book)
            +tinhMa412(nam,company,finance_book)+tinhMa413(nam,company,finance_book)
            +tinhMa414(nam,company,finance_book)+tinhMa415(nam,company,finance_book)
            +tinhMa416(nam,company,finance_book)+tinhMa417(nam,company,finance_book)
            +tinhMa418(nam,company,finance_book)+tinhMa419(nam,company,finance_book)
            +tinhMa420(nam,company,finance_book)+tinhMa421a(nam,company,finance_book)
            +tinhMa421b(nam,company,finance_book)+tinhMa422(nam,company,finance_book))

        elif maso == '411':
            return tinhMa411a(nam,company,finance_book)+tinhMa411b(nam,company,finance_book)
        elif maso == '411a':
            return tinhMa411a(nam,company,finance_book)
        elif maso == '411b':
            return tinhMa411b(nam,company,finance_book)
        elif maso == '412':
            return tinhMa412(nam,company,finance_book)
        elif maso == '413':
            return tinhMa413(nam,company,finance_book)
        elif maso == '414':
            return tinhMa414(nam,company,finance_book)
        elif maso == '415':
            return tinhMa415(nam,company,finance_book)
        elif maso == '416':
            return tinhMa416(nam,company,finance_book)
        elif maso == '417':
            return tinhMa417(nam,company,finance_book)
        elif maso == '418':
            return tinhMa418(nam,company,finance_book)
        elif maso == '419':
            return tinhMa419(nam,company,finance_book)
        elif maso == '420':
            return tinhMa420(nam,company,finance_book)
        elif maso == '421':
            return tinhMa421a(nam,company,finance_book)+tinhMa421b(nam,company,finance_book)
        elif maso == '421a':
            return tinhMa421a(nam,company,finance_book)
        elif maso == '421b':
            return tinhMa421b(nam,company,finance_book)
        elif maso == '422':
            return tinhMa422(nam,company,finance_book)
        elif maso == '430':
            return tinhMa431(nam,company,finance_book)+tinhMa432(nam,company,finance_book)
        elif maso == '431':
            return tinhMa431(nam,company,finance_book)
        elif maso == '432':
            return tinhMa432(nam,company,finance_book)
        elif maso == '440':
            return  (tinhMa311(nam,company,finance_book)+tinhMa312(nam,company,finance_book)
            +tinhMa313(nam,company,finance_book)+tinhMa314(nam,company,finance_book)
            +tinhMa315(nam,company,finance_book)+tinhMa316(nam,company,finance_book)
            +tinhMa317(nam,company,finance_book)+tinhMa318(nam,company,finance_book)
            +tinhMa319(nam,company,finance_book)+tinhMa320(nam,company,finance_book)
            +tinhMa321(nam,company,finance_book)+tinhMa322(nam,company,finance_book)
            +tinhMa323(nam,company,finance_book)+tinhMa324(nam,company,finance_book)+
                tinhMa331(nam,company,finance_book)+tinhMa332(nam,company,finance_book)
            +tinhMa333(nam,company,finance_book)+tinhMa334(nam,company,finance_book)
            +tinhMa335(nam,company,finance_book)+tinhMa336(nam,company,finance_book)
            +tinhMa337(nam,company,finance_book)+tinhMa338(nam,company,finance_book)
            +tinhMa339(nam,company,finance_book)+tinhMa340(nam,company,finance_book)
            +tinhMa341(nam,company,finance_book)+tinhMa342(nam,company,finance_book)
            +tinhMa343(nam,company,finance_book)+
                    tinhMa411a(nam,company,finance_book)+tinhMa411b(nam,company,finance_book)
            +tinhMa412(nam,company,finance_book)+tinhMa413(nam,company,finance_book)
            +tinhMa414(nam,company,finance_book)+tinhMa415(nam,company,finance_book)
            +tinhMa416(nam,company,finance_book)+tinhMa417(nam,company,finance_book)
            +tinhMa418(nam,company,finance_book)+tinhMa419(nam,company,finance_book)
            +tinhMa420(nam,company,finance_book)+tinhMa421a(nam,company,finance_book)
            +tinhMa421b(nam,company,finance_book)+tinhMa422(nam,company,finance_book)+
                tinhMa431(nam,company,finance_book)+tinhMa432(nam,company,finance_book))
    else:
        if maso == '100':
            return (tinhMa111_KhacYearly(nam,company,finance_book)+tinhMa112_KhacYearly(nam,company,finance_book)+
            tinhMa122_KhacYearly(nam,company,finance_book)+tinhMa121_KhacYearly(nam,company,finance_book)
                                                +tinhMa123_KhacYearly(nam,company,finance_book)+
            tinhMa131_KhacYearly(nam,company,finance_book)+tinhMa132_KhacYearly(nam,company,finance_book)
                +tinhMa133_KhacYearly(nam,company,finance_book)+tinhMa134_KhacYearly(nam,company,finance_book)
                +tinhMa135_KhacYearly(nam,company,finance_book)+tinhMa136_KhacYearly(nam,company,finance_book)
                +tinhMa137_KhacYearly(nam,company,finance_book)+tinhMa139_KhacYearly(nam,company,finance_book)+
            tinhMa141_KhacYearly(nam,company,finance_book)+tinhMa149_KhacYearly(nam,company,finance_book)+
            tinhMa151_KhacYearly(nam,company,finance_book)+tinhMa152_KhacYearly(nam,company,finance_book)
                +tinhMa153_KhacYearly(nam,company,finance_book)+tinhMa154_KhacYearly(nam,company,finance_book)
                +tinhMa155_KhacYearly(nam,company,finance_book))
        elif maso == '110':
            return tinhMa111_KhacYearly(nam,company,finance_book)+tinhMa112_KhacYearly(nam,company,finance_book)
        elif maso == '111':
            return tinhMa111_KhacYearly(nam,company,finance_book)
        elif maso == '112':
            return tinhMa112_KhacYearly(nam,company,finance_book)
        elif maso == '120':
            return   (tinhMa121_KhacYearly(nam,company,finance_book) + tinhMa122_KhacYearly(nam,company,finance_book) 
                        + tinhMa123_KhacYearly(nam,company,finance_book))
        elif maso == '121':
            return tinhMa121_KhacYearly(nam,company,finance_book)
        elif maso == '122':
            return tinhMa122_KhacYearly(nam,company,finance_book)
        elif maso == '123':
            return tinhMa123_KhacYearly(nam,company,finance_book)
        elif maso =='130':
            return (tinhMa131_KhacYearly(nam,company,finance_book) + tinhMa132_KhacYearly(nam,company,finance_book) 
                        +tinhMa133_KhacYearly(nam,company,finance_book) + tinhMa134_KhacYearly(nam,company,finance_book) 
                        + tinhMa135_KhacYearly(nam,company,finance_book) + tinhMa136_KhacYearly(nam,company,finance_book) 
                        + tinhMa137_KhacYearly(nam,company,finance_book) + tinhMa139_KhacYearly(nam,company,finance_book)
                    )   
        elif maso == '131':
            return tinhMa131_KhacYearly(nam,company,finance_book)
        elif maso == '132':
            return tinhMa132_KhacYearly(nam,company,finance_book)
        elif maso == '133':
            return tinhMa133_KhacYearly(nam,company,finance_book)
        elif maso == '134':
            return tinhMa134_KhacYearly(nam,company,finance_book)
        elif maso == '135':
            return tinhMa135_KhacYearly(nam,company,finance_book)
        elif maso == '136':
            return tinhMa136_KhacYearly(nam,company,finance_book)
        elif maso == '137':
            return tinhMa137_KhacYearly(nam,company,finance_book)
        elif maso == '139':
            return tinhMa139_KhacYearly(nam,company,finance_book)
        elif maso == '140':
            return (tinhMa141_KhacYearly(nam,company,finance_book) 
            + tinhMa149_KhacYearly(nam,company,finance_book))

        elif maso == '141':
            return tinhMa141_KhacYearly(nam,company,finance_book)
        elif maso == '149':
            return tinhMa149_KhacYearly(nam,company,finance_book)
        elif maso == '150':
            return (tinhMa151_KhacYearly(nam,company,finance_book) 
            + tinhMa152_KhacYearly(nam,company,finance_book) 
                    + tinhMa153_KhacYearly(nam,company,finance_book) 
                    + tinhMa154_KhacYearly(nam,company,finance_book) 
                    + tinhMa155_KhacYearly(nam,company,finance_book))
        elif maso == '151':
            return tinhMa151_KhacYearly(nam,company,finance_book)
        elif maso == '152':
            return tinhMa152_KhacYearly(nam,company,finance_book)
        elif maso == '153':
            return tinhMa153_KhacYearly(nam,company,finance_book)
        elif maso == '154':
            return tinhMa154_KhacYearly(nam,company,finance_book)
        elif maso == '155':
            return tinhMa155_KhacYearly(nam,company,finance_book)
        elif maso == '200':
            return (tinhMa211_KhacYearly(nam,company,finance_book)+tinhMa212_KhacYearly(nam,company,finance_book)
                +tinhMa213_KhacYearly(nam,company,finance_book)+tinhMa214_KhacYearly(nam,company,finance_book)
                +tinhMa215_KhacYearly(nam,company,finance_book)+tinhMa216_KhacYearly(nam,company,finance_book)
                +tinhMa219_KhacYearly(nam,company,finance_book)+
                    tinhMa222_KhacYearly(nam,company,finance_book)+tinhMa223_KhacYearly(nam,company,finance_book)
                +tinhMa225_KhacYearly(nam,company,finance_book)+tinhMa226_KhacYearly(nam,company,finance_book)
                +tinhMa229_KhacYearly(nam,company,finance_book)+tinhMa228_KhacYearly(nam,company,finance_book)+
                    tinhMa231_KhacYearly(nam,company,finance_book)+tinhMa232_KhacYearly(nam,company,finance_book)+
                    tinhMa241_KhacYearly(nam,company,finance_book)+tinhMa242_KhacYearly(nam,company,finance_book)+
                    tinhMa251_KhacYearly(nam,company,finance_book)+tinhMa252_KhacYearly(nam,company,finance_book)
                +tinhMa253_KhacYearly(nam,company,finance_book)+tinhMa254_KhacYearly(nam,company,finance_book)
                +tinhMa255_KhacYearly(nam,company,finance_book)+
                    tinhMa261_KhacYearly(nam,company,finance_book)+tinhMa262_KhacYearly(nam,company,finance_book)
                +tinhMa263_KhacYearly(nam,company,finance_book)+tinhMa268_KhacYearly(nam,company,finance_book))
        elif maso == '210':
            return (tinhMa211_KhacYearly(nam,company,finance_book)+tinhMa212_KhacYearly(nam,company,finance_book)
            +tinhMa213_KhacYearly(nam,company,finance_book)+tinhMa214_KhacYearly(nam,company,finance_book)
            +tinhMa215_KhacYearly(nam,company,finance_book)+tinhMa216_KhacYearly(nam,company,finance_book)
            +tinhMa219_KhacYearly(nam,company,finance_book))
        elif maso == '211':
            return tinhMa211_KhacYearly(nam,company,finance_book)
        elif maso == '212':
            return tinhMa212_KhacYearly(nam,company,finance_book)
        elif maso == '213':
            return tinhMa213_KhacYearly(nam,company,finance_book)
        elif maso == '214':
            return tinhMa214_KhacYearly(nam,company,finance_book)
        elif maso == '215':
            return tinhMa215_KhacYearly(nam,company,finance_book)
        elif maso == '216':
            return tinhMa216_KhacYearly(nam,company,finance_book)
        elif maso == '219':
            return tinhMa219_KhacYearly(nam,company,finance_book)
        elif maso == '220':
            return (tinhMa222_KhacYearly(nam,company,finance_book)
            +tinhMa223_KhacYearly(nam,company,finance_book)
            +tinhMa225_KhacYearly(nam,company,finance_book)
            +tinhMa226_KhacYearly(nam,company,finance_book)
            +tinhMa229_KhacYearly(nam,company,finance_book)
            +tinhMa228_KhacYearly(nam,company,finance_book))

        elif maso == '221':
            return (tinhMa222_KhacYearly(nam,company,finance_book)
            +tinhMa223_KhacYearly(nam,company,finance_book))
        elif maso == '222':
            return tinhMa222_KhacYearly(nam,company,finance_book)
        elif maso == '223':
            return tinhMa223_KhacYearly(nam,company,finance_book)
        elif maso == '224':
            return (tinhMa225_KhacYearly(nam,company,finance_book)
            +tinhMa226_KhacYearly(nam,company,finance_book))
        elif maso == '225':
            return tinhMa225_KhacYearly(nam,company,finance_book)
        elif maso == '226':
            return tinhMa226_KhacYearly(nam,company,finance_book)

        elif maso == '227':
            return (tinhMa229_KhacYearly(nam,company,finance_book)
            +tinhMa228_KhacYearly(nam,company,finance_book))
        elif maso == '228':
            return tinhMa228_KhacYearly(nam,company,finance_book)
        elif maso == '229':
            return tinhMa229_KhacYearly(nam,company,finance_book)
        elif maso == '230':
            return (tinhMa231_KhacYearly(nam,company,finance_book)
            +tinhMa232_KhacYearly(nam,company,finance_book))
        elif maso == '231':
            return tinhMa231_KhacYearly(nam,company,finance_book)
        elif maso == '232':
            return tinhMa232_KhacYearly(nam,company,finance_book)
        elif maso == '240':
            return (tinhMa241_KhacYearly(nam,company,finance_book)
            +tinhMa242_KhacYearly(nam,company,finance_book))
        elif maso == '241':
            return tinhMa241_KhacYearly(nam,company,finance_book) 
        elif maso == '242':
            return tinhMa242_KhacYearly(nam,company,finance_book)
        elif maso == '250':
            return (
                tinhMa251_KhacYearly(nam,company,finance_book)
                +tinhMa252_KhacYearly(nam,company,finance_book)
                +tinhMa253_KhacYearly(nam,company,finance_book)
                +tinhMa254_KhacYearly(nam,company,finance_book)
                +tinhMa255_KhacYearly(nam,company,finance_book))

        elif maso == '251':
            return tinhMa251_KhacYearly(nam,company,finance_book)
        elif maso == '252':
            return tinhMa252_KhacYearly(nam,company,finance_book)
        elif maso == '253':
            return tinhMa253_KhacYearly(nam,company,finance_book)
        elif maso == '254':
            return tinhMa254_KhacYearly(nam,company,finance_book)
        elif maso == '255':
            return tinhMa255_KhacYearly(nam,company,finance_book)
        elif maso == '260':
            return (tinhMa261_KhacYearly(nam,company,finance_book)+tinhMa262_KhacYearly(nam,company,finance_book)
            +tinhMa263_KhacYearly(nam,company,finance_book)+tinhMa268_KhacYearly(nam,company,finance_book))
        elif maso == '261':
            return tinhMa261_KhacYearly(nam,company,finance_book)
        elif maso == '262':
            return tinhMa262_KhacYearly(nam,company,finance_book)
        elif maso == '263':
            return tinhMa263_KhacYearly(nam,company,finance_book)
        elif maso == '268':
            return tinhMa268_KhacYearly(nam,company,finance_book)
        elif maso == '270':
            return (tinhMa111_KhacYearly(nam,company,finance_book)+tinhMa112_KhacYearly(nam,company,finance_book)+
            tinhMa122_KhacYearly(nam,company,finance_book)+tinhMa121_KhacYearly(nam,company,finance_book)
                                                +tinhMa123_KhacYearly(nam,company,finance_book)+
            tinhMa131_KhacYearly(nam,company,finance_book)+tinhMa132_KhacYearly(nam,company,finance_book)
                +tinhMa133_KhacYearly(nam,company,finance_book)+tinhMa134_KhacYearly(nam,company,finance_book)
                +tinhMa135_KhacYearly(nam,company,finance_book)+tinhMa136_KhacYearly(nam,company,finance_book)
                +tinhMa137_KhacYearly(nam,company,finance_book)+tinhMa139_KhacYearly(nam,company,finance_book)+
            tinhMa141_KhacYearly(nam,company,finance_book)+tinhMa149_KhacYearly(nam,company,finance_book)+
            tinhMa151_KhacYearly(nam,company,finance_book)+tinhMa152_KhacYearly(nam,company,finance_book)
                +tinhMa153_KhacYearly(nam,company,finance_book)+tinhMa154_KhacYearly(nam,company,finance_book)
                +tinhMa155_KhacYearly(nam,company,finance_book)+
                    tinhMa211_KhacYearly(nam,company,finance_book)+tinhMa212_KhacYearly(nam,company,finance_book)
                +tinhMa213_KhacYearly(nam,company,finance_book)+tinhMa214_KhacYearly(nam,company,finance_book)
                +tinhMa215_KhacYearly(nam,company,finance_book)+tinhMa216_KhacYearly(nam,company,finance_book)
                +tinhMa219_KhacYearly(nam,company,finance_book)+
                    tinhMa222_KhacYearly(nam,company,finance_book)+tinhMa223_KhacYearly(nam,company,finance_book)
                +tinhMa225_KhacYearly(nam,company,finance_book)+tinhMa226_KhacYearly(nam,company,finance_book)
                +tinhMa229_KhacYearly(nam,company,finance_book)+tinhMa228_KhacYearly(nam,company,finance_book)+
                    tinhMa231_KhacYearly(nam,company,finance_book)+tinhMa232_KhacYearly(nam,company,finance_book)+
                    tinhMa241_KhacYearly(nam,company,finance_book)+tinhMa242_KhacYearly(nam,company,finance_book)+
                    tinhMa251_KhacYearly(nam,company,finance_book)+tinhMa252_KhacYearly(nam,company,finance_book)
                +tinhMa253_KhacYearly(nam,company,finance_book)+tinhMa254_KhacYearly(nam,company,finance_book)
                +tinhMa255_KhacYearly(nam,company,finance_book)+
                    tinhMa261_KhacYearly(nam,company,finance_book)+tinhMa262_KhacYearly(nam,company,finance_book)
                +tinhMa263_KhacYearly(nam,company,finance_book)+tinhMa268_KhacYearly(nam,company,finance_book))
        elif maso == '300':
            return (tinhMa311_KhacYearly(nam,company,finance_book)+tinhMa312_KhacYearly(nam,company,finance_book)
            +tinhMa313_KhacYearly(nam,company,finance_book)+tinhMa314_KhacYearly(nam,company,finance_book)
            +tinhMa315_KhacYearly(nam,company,finance_book)+tinhMa316_KhacYearly(nam,company,finance_book)
            +tinhMa317_KhacYearly(nam,company,finance_book)+tinhMa318_KhacYearly(nam,company,finance_book)
            +tinhMa319_KhacYearly(nam,company,finance_book)+tinhMa320_KhacYearly(nam,company,finance_book)
            +tinhMa321_KhacYearly(nam,company,finance_book)+tinhMa322_KhacYearly(nam,company,finance_book)
            +tinhMa323_KhacYearly(nam,company,finance_book)+tinhMa324_KhacYearly(nam,company,finance_book)+
                tinhMa331_KhacYearly(nam,company,finance_book)+tinhMa332_KhacYearly(nam,company,finance_book)
            +tinhMa333_KhacYearly(nam,company,finance_book)+tinhMa334_KhacYearly(nam,company,finance_book)
            +tinhMa335_KhacYearly(nam,company,finance_book)+tinhMa336_KhacYearly(nam,company,finance_book)
            +tinhMa337_KhacYearly(nam,company,finance_book)+tinhMa338_KhacYearly(nam,company,finance_book)
            +tinhMa339_KhacYearly(nam,company,finance_book)+tinhMa340_KhacYearly(nam,company,finance_book)
            +tinhMa341_KhacYearly(nam,company,finance_book)+tinhMa342_KhacYearly(nam,company,finance_book)
            +tinhMa343_KhacYearly(nam,company,finance_book))
        elif maso == '310':
            return (tinhMa311_KhacYearly(nam,company,finance_book)+tinhMa312_KhacYearly(nam,company,finance_book)
            +tinhMa313_KhacYearly(nam,company,finance_book)+tinhMa314_KhacYearly(nam,company,finance_book)
            +tinhMa315_KhacYearly(nam,company,finance_book)+tinhMa316_KhacYearly(nam,company,finance_book)
            +tinhMa317_KhacYearly(nam,company,finance_book)+tinhMa318_KhacYearly(nam,company,finance_book)
            +tinhMa319_KhacYearly(nam,company,finance_book)+tinhMa320_KhacYearly(nam,company,finance_book)
            +tinhMa321_KhacYearly(nam,company,finance_book)+tinhMa322_KhacYearly(nam,company,finance_book)
            +tinhMa323_KhacYearly(nam,company,finance_book)+tinhMa324_KhacYearly(nam,company,finance_book))

        elif maso == '311':
            return tinhMa311_KhacYearly(nam,company,finance_book)
        elif maso == '312':
            return tinhMa312_KhacYearly(nam,company,finance_book)
        elif maso == '313':
            return tinhMa313_KhacYearly(nam,company,finance_book)
        elif maso == '314':
            return tinhMa314_KhacYearly(nam,company,finance_book)
        elif maso == '315':
            return tinhMa315_KhacYearly(nam,company,finance_book)
        elif maso == '316':
            return tinhMa316_KhacYearly(nam,company,finance_book)
        elif maso == '317':
            return tinhMa317_KhacYearly(nam,company,finance_book)
        elif maso == '318':
            return tinhMa318_KhacYearly(nam,company,finance_book)
        elif maso == '319':
            return tinhMa319_KhacYearly(nam,company,finance_book)
        elif maso == '320':
            return tinhMa320_KhacYearly(nam,company,finance_book)
        elif maso == '321':
            return tinhMa321_KhacYearly(nam,company,finance_book)
        elif maso == '322':
            return tinhMa322_KhacYearly(nam,company,finance_book)
        elif maso == '323':
            return tinhMa323_KhacYearly(nam,company,finance_book)
        elif maso == '324':
            return tinhMa324_KhacYearly(nam,company,finance_book)
        elif maso == '330':
            return (tinhMa331_KhacYearly(nam,company,finance_book)+tinhMa332_KhacYearly(nam,company,finance_book)
            +tinhMa333_KhacYearly(nam,company,finance_book)+tinhMa334_KhacYearly(nam,company,finance_book)
            +tinhMa335_KhacYearly(nam,company,finance_book)+tinhMa336_KhacYearly(nam,company,finance_book)
            +tinhMa337_KhacYearly(nam,company,finance_book)+tinhMa338_KhacYearly(nam,company,finance_book)
            +tinhMa339_KhacYearly(nam,company,finance_book)+tinhMa340_KhacYearly(nam,company,finance_book)
            +tinhMa341_KhacYearly(nam,company,finance_book)+tinhMa342_KhacYearly(nam,company,finance_book)
            +tinhMa343_KhacYearly(nam,company,finance_book))
        elif maso == '331':
            return tinhMa331_KhacYearly(nam,company,finance_book)
        elif maso == '332':
            return tinhMa332_KhacYearly(nam,company,finance_book)
        elif maso == '333':
            return tinhMa333_KhacYearly(nam,company,finance_book)
        elif maso == '334':
            return tinhMa334_KhacYearly(nam,company,finance_book)
        elif maso == '335':
            return tinhMa335_KhacYearly(nam,company,finance_book)
        elif maso == '336':
            return tinhMa336_KhacYearly(nam,company,finance_book)
        elif maso == '337':
            return tinhMa337_KhacYearly(nam,company,finance_book)
        elif maso == '338':
            return tinhMa338_KhacYearly(nam,company,finance_book)
        elif maso == '339':
            return tinhMa339_KhacYearly(nam,company,finance_book)
        elif maso == '340':
            return tinhMa340_KhacYearly(nam,company,finance_book)
        elif maso == '341':
            return tinhMa341_KhacYearly(nam,company,finance_book)
        elif maso == '342':
            return tinhMa342_KhacYearly(nam,company,finance_book)
        elif maso == '343':
            return tinhMa343_KhacYearly(nam,company,finance_book)
        elif maso == '400':
            return (tinhMa411a_KhacYearly(nam,company,finance_book)+tinhMa411b_KhacYearly(nam,company,finance_book)
            +tinhMa412_KhacYearly(nam,company,finance_book)+tinhMa413_KhacYearly(nam,company,finance_book)
            +tinhMa414_KhacYearly(nam,company,finance_book)+tinhMa415_KhacYearly(nam,company,finance_book)
            +tinhMa416_KhacYearly(nam,company,finance_book)+tinhMa417_KhacYearly(nam,company,finance_book)
            +tinhMa418_KhacYearly(nam,company,finance_book)+tinhMa419_KhacYearly(nam,company,finance_book)
            +tinhMa420_KhacYearly(nam,company,finance_book)+tinhMa421a_KhacYearly(nam,company,finance_book)
            +tinhMa421b_KhacYearly(nam,company,finance_book)+tinhMa422_KhacYearly(nam,company,finance_book)+
                tinhMa431_KhacYearly(nam,company,finance_book)+tinhMa432_KhacYearly(nam,company,finance_book))

        elif maso == '410':
            return (tinhMa411a_KhacYearly(nam,company,finance_book)+tinhMa411b_KhacYearly(nam,company,finance_book)
            +tinhMa412_KhacYearly(nam,company,finance_book)+tinhMa413_KhacYearly(nam,company,finance_book)
            +tinhMa414_KhacYearly(nam,company,finance_book)+tinhMa415_KhacYearly(nam,company,finance_book)
            +tinhMa416_KhacYearly(nam,company,finance_book)+tinhMa417_KhacYearly(nam,company,finance_book)
            +tinhMa418_KhacYearly(nam,company,finance_book)+tinhMa419_KhacYearly(nam,company,finance_book)
            +tinhMa420_KhacYearly(nam,company,finance_book)+tinhMa421a_KhacYearly(nam,company,finance_book)
            +tinhMa421b_KhacYearly(nam,company,finance_book)+tinhMa422_KhacYearly(nam,company,finance_book))

        elif maso == '411':
            return tinhMa411a_KhacYearly(nam,company,finance_book)+tinhMa411b_KhacYearly(nam,company,finance_book)
        elif maso == '411a':
            return tinhMa411a_KhacYearly(nam,company,finance_book)
        elif maso == '411b':
            return tinhMa411b_KhacYearly(nam,company,finance_book)
        elif maso == '412':
            return tinhMa412_KhacYearly(nam,company,finance_book)
        elif maso == '413':
            return tinhMa413_KhacYearly(nam,company,finance_book)
        elif maso == '414':
            return tinhMa414_KhacYearly(nam,company,finance_book)
        elif maso == '415':
            return tinhMa415_KhacYearly(nam,company,finance_book)
        elif maso == '416':
            return tinhMa416_KhacYearly(nam,company,finance_book)
        elif maso == '417':
            return tinhMa417_KhacYearly(nam,company,finance_book)
        elif maso == '418':
            return tinhMa418_KhacYearly(nam,company,finance_book)
        elif maso == '419':
            return tinhMa419_KhacYearly(nam,company,finance_book)
        elif maso == '420':
            return tinhMa420_KhacYearly(nam,company,finance_book)
        elif maso == '421':
            return tinhMa421a_KhacYearly(nam,company,finance_book)+tinhMa421b_KhacYearly(nam,company,finance_book)
        elif maso == '421a':
            return tinhMa421a_KhacYearly(nam,company,finance_book)
        elif maso == '421b':
            return tinhMa421b_KhacYearly(nam,company,finance_book)
        elif maso == '422':
            return tinhMa422_KhacYearly(nam,company,finance_book)
        elif maso == '430':
            return tinhMa431_KhacYearly(nam,company,finance_book)+tinhMa432_KhacYearly(nam,company,finance_book)
        elif maso == '431':
            return tinhMa431_KhacYearly(nam,company,finance_book)
        elif maso == '432':
            return tinhMa432_KhacYearly(nam,company,finance_book)
        elif maso == '440':
            return  (tinhMa311_KhacYearly(nam,company,finance_book)+tinhMa312_KhacYearly(nam,company,finance_book)
            +tinhMa313_KhacYearly(nam,company,finance_book)+tinhMa314_KhacYearly(nam,company,finance_book)
            +tinhMa315_KhacYearly(nam,company,finance_book)+tinhMa316_KhacYearly(nam,company,finance_book)
            +tinhMa317_KhacYearly(nam,company,finance_book)+tinhMa318_KhacYearly(nam,company,finance_book)
            +tinhMa319_KhacYearly(nam,company,finance_book)+tinhMa320_KhacYearly(nam,company,finance_book)
            +tinhMa321_KhacYearly(nam,company,finance_book)+tinhMa322_KhacYearly(nam,company,finance_book)
            +tinhMa323_KhacYearly(nam,company,finance_book)+tinhMa324_KhacYearly(nam,company,finance_book)+
                tinhMa331_KhacYearly(nam,company,finance_book)+tinhMa332_KhacYearly(nam,company,finance_book)
            +tinhMa333_KhacYearly(nam,company,finance_book)+tinhMa334_KhacYearly(nam,company,finance_book)
            +tinhMa335_KhacYearly(nam,company,finance_book)+tinhMa336_KhacYearly(nam,company,finance_book)
            +tinhMa337_KhacYearly(nam,company,finance_book)+tinhMa338_KhacYearly(nam,company,finance_book)
            +tinhMa339_KhacYearly(nam,company,finance_book)+tinhMa340_KhacYearly(nam,company,finance_book)
            +tinhMa341_KhacYearly(nam,company,finance_book)+tinhMa342_KhacYearly(nam,company,finance_book)
            +tinhMa343_KhacYearly(nam,company,finance_book)+
                    tinhMa411a_KhacYearly(nam,company,finance_book)+tinhMa411b_KhacYearly(nam,company,finance_book)
            +tinhMa412_KhacYearly(nam,company,finance_book)+tinhMa413_KhacYearly(nam,company,finance_book)
            +tinhMa414_KhacYearly(nam,company,finance_book)+tinhMa415_KhacYearly(nam,company,finance_book)
            +tinhMa416_KhacYearly(nam,company,finance_book)+tinhMa417_KhacYearly(nam,company,finance_book)
            +tinhMa418_KhacYearly(nam,company,finance_book)+tinhMa419_KhacYearly(nam,company,finance_book)
            +tinhMa420_KhacYearly(nam,company,finance_book)+tinhMa421a_KhacYearly(nam,company,finance_book)
            +tinhMa421b_KhacYearly(nam,company,finance_book)+tinhMa422_KhacYearly(nam,company,finance_book)+
                tinhMa431_KhacYearly(nam,company,finance_book)+tinhMa432_KhacYearly(nam,company,finance_book))
        else:
            return 0
def tinhMa111_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return ((tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'111%%',company,finance_book)) 
            + (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'112%%',company,finance_book)) 
            + (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'113%%',company,finance_book)))
    else:
        return ((tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'111%%',company,finance_book)) 
                + (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'112%%',company,finance_book)) 
                + (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'113%%',company,finance_book)))
def tinhMa112_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12811%%',company,finance_book) 
            + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12881%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12811%%',company,finance_book) 
                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12881%%',company,finance_book))
def tinhMa121_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'121%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'121%%',company,finance_book)
def tinhMa122_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'2291%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'2291%%',company,finance_book)
def tinhMa123_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return      (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12812%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12821%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12882%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12812%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12821%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12882%%',company,finance_book))
def tinhMa131_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return tinh_No_Yearly_Finance_Book_Party_Pos_Opening(nam,'1311%',company,finance_book)
    else:
        return tinh_No_Yearly_Finance_Book_Party_Pos_Mid(nam,'1311%',company,finance_book)

def tinhMa132_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return tinh_No_Yearly_Finance_Book_Party_Pos_Opening(nam,'3311%%',company,finance_book)
    else:
        return tinh_No_Yearly_Finance_Book_Party_Pos_Mid(nam,'3311%%',company,finance_book)

def tinhMa133_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'13621%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'13631%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'13681%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'13621%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'13631%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'13681%%',company,finance_book))

def tinhMa134_KhacYearly(nam,company,finance_book):
    if nam.from_date.month == 1:
        return tinh_No_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'337%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'337%%',company,finance_book)

def tinhMa135_KhacYearly(nam, company,finance_book):
    if nam.from_date.month == 1:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12831%%',company,finance_book)
    else:   
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12831%%',company,finance_book)

def tinhMa136_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1411%%',company,finance_book)
                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'2441%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'13851%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'13881%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'334%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'3381%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'3382%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'3383%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'3384%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'33851%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'3386%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'33871%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'33881%%',company,finance_book)
                )
    else:
        return  (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1411%%',company,finance_book)
                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'2441%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'13851%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'13881%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'334%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'3381%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'3382%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'3383%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'3384%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'33851%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'3386%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'33871%%',company,finance_book)
                + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'33881%%',company,finance_book)
                )  

def tinhMa137_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'22931%%',company,finance_book)
    else:
        return  tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'22931%%',company,finance_book)
def tinhMa139_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'1381%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'1381%%',company,finance_book)
def tinhMa141_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'151%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'152%%',company,finance_book)
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'155%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'156%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'157%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'158%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1531%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1532%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1533%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'15341%%',company,finance_book)
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1541%%',company,finance_book) 
                                )
    else:
        return  (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'151%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'152%%',company,finance_book)
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'155%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'156%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'157%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'158%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1531%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1532%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1533%%',company,finance_book) 
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'15341%%',company,finance_book)
                                + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1541%%',company,finance_book) 
                                )
def tinhMa149_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'22941%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'22941%%',company,finance_book)
def tinhMa151_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'2421%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'2421%%',company,finance_book)
def tinhMa152_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'133%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'133%%',company,finance_book)
def tinhMa153_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'333%%',company,finance_book) 
    else:
        return  tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'333%%',company,finance_book)
def tinhMa154_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'171%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'171%%',company,finance_book)
def tinhMa155_KhacYearly(nam, company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'22881%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'22881%%',company,finance_book)


def tinhMa211_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Yearly_Finance_Book_Party_Pos_Opening(nam,'1312%%',company,finance_book)
    else:
        return  tinh_No_Yearly_Finance_Book_Party_Pos_Mid(nam,'1312%%',company,finance_book)
def tinhMa212_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Yearly_Finance_Book_Party_Pos_Opening(nam,'3312%%',company,finance_book)
    else:
        return  tinh_No_Yearly_Finance_Book_Party_Pos_Mid(nam,'3312%%',company,finance_book)
def tinhMa213_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1361%%',company,finance_book)
    else:
        return  tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1361%%',company,finance_book)
def tinhMa214_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'13622%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'13632%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'13682%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'13622%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'13632%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'13682%%',company,finance_book))
def tinhMa215_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12832%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12832%%',company,finance_book)
    
def tinhMa216_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'13852%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'13882%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'1412%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'2442%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'33852%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'33872%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Opening(nam,'33882%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'13852%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'13882%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'1412%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'2442%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'33852%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'33872%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_If_Pos_ma313_Mid(nam,'33882%%',company,finance_book))
    
def tinhMa219_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'22932%%',company,finance_book) 
    else:
        return tinh_No_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'22932%%',company,finance_book) 
    
def tinhMa222_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'211%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'211%%',company,finance_book)
    
def tinhMa223_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'2141%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'2141%%',company,finance_book)
    
def tinhMa225_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'212%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'212%%',company,finance_book)
    
def tinhMa226_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'2142%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'2142%%',company,finance_book)
    
def tinhMa228_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'213%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'213%%',company,finance_book)
    
def tinhMa229_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'2143%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'2143%%',company,finance_book)
    
def tinhMa231_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'217%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'217%%',company,finance_book)
    
def tinhMa232_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'2147%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'2147%%',company,finance_book)
    
def tinhMa241_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'1542%%',company,finance_book) 
                + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'22942%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'1542%%',company,finance_book) 
                + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'22942%%',company,finance_book))
    
def tinhMa242_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'241%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'241%%',company,finance_book)
    
def tinhMa251_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'221%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'221%%',company,finance_book)
    
def tinhMa252_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'222%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'222%%',company,finance_book)
    
def tinhMa253_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'2281%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'2281%%',company,finance_book)
    
def tinhMa254_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Opening(nam,'2292%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Nega_PostingDate_Mid(nam,'2292%%',company,finance_book)
    
def tinhMa255_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12813%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12822%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'12883%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12813%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12822%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'12883%%',company,finance_book))
    
def tinhMa261_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'2422%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'2422%%',company,finance_book)
    
def tinhMa262_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'243%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'243%%',company,finance_book)
    
def tinhMa263_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'22943%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'15342%%',company,finance_book))
    else:
        return (tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'22943%%',company,finance_book) 
                    + tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'15342%%',company,finance_book))
    
def tinhMa268_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1: 
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'22882%%',company,finance_book)
    else:
        return tinh_No_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'22882%%',company,finance_book)

def tinhMa311_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Opening(nam,'3311%%',company,finance_book)
    else: 
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Mid(nam,'3311%%',company,finance_book)
def tinhMa312_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Opening(nam,'1311%%',company,finance_book)
    else:
         return tinh_Co_Yearly_Finance_Book_Party_Pos_Mid(nam,'1311%%',company,finance_book)
def tinhMa313_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'333%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'333%%',company,finance_book)
def tinhMa314_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'334%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'334%%',company,finance_book)
def tinhMa315_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'3351%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'3351%%',company,finance_book)
def tinhMa316_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'33621%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'33631%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'33681%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'33621%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'33631%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'33681%%',company,finance_book))              
def tinhMa317_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'337%%',company,finance_book)
    else:    
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'337%%',company,finance_book)
def tinhMa318_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'33871%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'33871%%',company,finance_book)
def tinhMa319_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'3381%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'3382%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'3383%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'3384%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'33851%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'3386%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'33881%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'1381%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'13851%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'13881%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'3441%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'3381%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'3382%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'3383%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'3384%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'33851%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'3386%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'33881%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'1381%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'13851%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'13881%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'3441%%',company,finance_book))
def tinhMa320_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return(tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'34111%%',company,finance_book) 
                        + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'34121%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'343111%%',company,finance_book))
    else:
        return(tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'34111%%',company,finance_book) 
                        + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'34121%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'343111%%',company,finance_book))
def tinhMa321_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35211%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35221%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35231%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35241%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35211%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35221%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35231%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35241%%',company,finance_book))
def tinhMa322_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'353%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'353%%',company,finance_book)
def tinhMa323_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'357%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'357%%',company,finance_book)  
def tinhMa324_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'171%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'171%%',company,finance_book)
def tinhMa331_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Opening(nam,'3312%%',company,finance_book)
    else:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Mid(nam,'3312%%',company,finance_book)
def tinhMa332_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Opening(nam,'1312%%',company,finance_book)
    else:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Mid(nam,'1312%%',company,finance_book)
def tinhMa333_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'3352%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'3352%%',company,finance_book)
def tinhMa334_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'3361%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'3361%%',company,finance_book)
def tinhMa335_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'33622%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'33632%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'33682%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'33622%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'33632%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'33682%%',company,finance_book))
def tinhMa336_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Opening(nam,'33872%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_If_Pos_PostingDate_Mid(nam,'33872%%',company,finance_book)
def tinhMa337_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'3442%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'33852%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_If_Pos_ma313_Opening(nam,'33882%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'3442%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'33852%%',company,finance_book) 
                    + tinh_Co_Cua_Yearly_If_Pos_ma313_Mid(nam,'33882%%',company,finance_book))
def tinhMa338_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'34112%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'34122%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'343112%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'34312%%',company,finance_book)  
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'34313%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'34112%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'34122%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'343112%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'34312%%',company,finance_book)  
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'34313%%',company,finance_book))
def tinhMa339_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'3432%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'3432%%',company,finance_book)
def tinhMa340_KhacYearly  (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'411122%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'411122%%',company,finance_book)
def tinhMa341_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'347%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'347%%',company,finance_book)
def tinhMa342_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35212%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35222%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35232%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'35242%%',company,finance_book)) 
    else:
         return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35212%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35222%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35232%%',company,finance_book) 
    + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'35242%%',company,finance_book)) 
def tinhMa343_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'356%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'356%%',company,finance_book)

def tinhMa411a_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Opening(nam,'41111%%',company,finance_book)
    else:
        return tinh_Co_Yearly_Finance_Book_Party_Pos_Mid(nam,'41111%%',company,finance_book)
def tinhMa411b_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'411121%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'411121%%',company,finance_book)
def tinhMa412_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'4112%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'4112%%',company,finance_book)
def tinhMa413_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'4113%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'4113%%',company,finance_book)
def tinhMa414_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'4118%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'4118%%',company,finance_book)
def tinhMa415_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'419%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'419%%',company,finance_book)
def tinhMa416_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'412%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'412%%',company,finance_book)
def tinhMa417_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'413%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'413%%',company,finance_book)
def tinhMa418_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'414%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'414%%',company,finance_book)
def tinhMa419_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
       return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'417%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'417%%',company,finance_book)
def tinhMa420_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'418%%',company,finance_book)
    else:   
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'418%%',company,finance_book)
def tinhMa421a_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'4211%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'4211%%',company,finance_book)
def tinhMa421b_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'4212%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'4212%%',company,finance_book)
def tinhMa422_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'441%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'441%%',company,finance_book)
def tinhMa431_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'461%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'161%%',company,finance_book))
    else:
        return (tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'461%%',company,finance_book) 
            + tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'161%%',company,finance_book))
def tinhMa432_KhacYearly (nam,company,finance_book):
    if nam.from_date.month ==1:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Opening(nam,'466%%',company,finance_book)
    else:
        return tinh_Co_Cua_Yearly_Finance_Book_PostingDate_Mid(nam,'466%%',company,finance_book)  
 

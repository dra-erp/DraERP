# Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
        get_checks_for_pl_and_bs_accounts,
)


def post_depreciation_entries(date=None):
    # Return if automatic booking of asset depreciation is disabled
    if not cint(frappe.db.get_value("Accounts Settings", None, "book_asset_depreciation_entry_automatically")):
        return

    if not date:
        date = today()
    for iat in get_depreciable_iat(date):
        make_depreciation_entry(iat, date)
        frappe.db.commit()

def get_depreciable_iat(date):
    return frappe.db.sql_list("""select a.name
		from `tabIaT` a, `tabDepreciation Schedule` ds
		where a.name = ds.parent and a.docstatus=1 and ds.schedule_date<=%s and a.calculate_depreciation = 1
			and a.status in ('Submitted', 'Partially Depreciated')
			and ifnull(ds.journal_entry, '')=''""", date)

@frappe.whitelist()
def make_depreciation_entry(iat_name, date=None):
    frappe.has_permission('Journal Entry', throw=True)

    if not date:
        date = today()

    iat = frappe.get_doc("IaT", iat_name)
    iat_account, accumulated_depreciation_account, depreciation_expense_account = \
            get_depreciation_accounts(iat)

    depreciation_cost_center, depreciation_series = frappe.get_cached_value('Company',  iat.company,
            ["depreciation_cost_center", "series_for_depreciation_entry"])

    depreciation_cost_center = iat.cost_center or depreciation_cost_center

    accounting_dimensions = get_checks_for_pl_and_bs_accounts()

    for d in iat.get("schedules"):
        if not d.journal_entry and getdate(d.schedule_date) <= getdate(date):
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Depreciation Entry"
            je.naming_series = depreciation_series
            je.posting_date = d.schedule_date
            je.company = iat.company
            je.finance_book = d.finance_book
            je.remark = "Depreciation Entry against {0} worth {1}".format(iat_name, d.depreciation_amount)

            credit_account, debit_account = get_credit_and_debit_accounts(accumulated_depreciation_account, depreciation_expense_account)
            # day la comment hello Cuong alo
            credit_entry = {
                    "account": credit_account,
                    "credit_in_account_currency": d.depreciation_amount,
                    "reference_type": "IaT",
                    "reference_name": iat.name,
                    "cost_center": depreciation_cost_center
            }

            debit_entry = {
                    "account": debit_account,
                    "debit_in_account_currency": d.depreciation_amount,
                    "reference_type": "IaT",
                    "reference_name": iat.name,
                    "cost_center": depreciation_cost_center
            }


            for dimension in accounting_dimensions:
                if (iat.get(dimension['fieldname']) or dimension.get('mandatory_for_bs')):
                    credit_entry.update({
                            dimension['fieldname']: iat.get(dimension['fieldname']) or dimension.get('default_dimension')
                    })

                if (iat.get(dimension['fieldname']) or dimension.get('mandatory_for_pl')):
                    debit_entry.update({
                            dimension['fieldname']: iat.get(dimension['fieldname']) or dimension.get('default_dimension')
                    })


            je.append("accounts", credit_entry)

            je.append("accounts", debit_entry)

            je.flags.ignore_permissions = True
            je.save()



            if not je.meta.get_workflow():
                je.submit()

            d.db_set("journal_entry", je.name)



            idx = cint(d.finance_book_id)

            finance_books = iat.get('finance_books')[idx - 1]
            finance_books.value_after_depreciation -= d.depreciation_amount
            finance_books.db_update()

    iat.set_status()

    return iat

def get_depreciation_accounts(iat):
    iat_account = accumulated_depreciation_account = depreciation_expense_account = None

    accounts = frappe.db.get_value("IaT Category Account",
            filters={'parent': iat.tools_category, 'company_name': iat.company},
            fieldname = ['iat_account', 'accumulated_depreciation_account',
                    'depreciation_expense_account'], as_dict=1)

    if accounts:
        iat_account = accounts.iat_account
        accumulated_depreciation_account = accounts.accumulated_depreciation_account
        depreciation_expense_account = accounts.depreciation_expense_account

    if not accumulated_depreciation_account or not depreciation_expense_account:
        accounts = frappe.get_cached_value('Company',  iat.company,
                ["accumulated_depreciation_account", "depreciation_expense_account"])

        if not accumulated_depreciation_account:
            accumulated_depreciation_account = accounts[0]
        if not depreciation_expense_account:
            depreciation_expense_account = accounts[1]

    if not iat_account or not accumulated_depreciation_account or not depreciation_expense_account:
        frappe.throw(_("Please set Depreciation related Accounts in Tools Category {0} or Company {1}")
                .format(iat.tools_category, iat.company))

    return iat_account, accumulated_depreciation_account, depreciation_expense_account

def get_credit_and_debit_accounts(accumulated_depreciation_account, depreciation_expense_account):
    root_type = frappe.get_value("Account", depreciation_expense_account, "root_type")

    if root_type == "Expense":
        credit_account = accumulated_depreciation_account
        debit_account = depreciation_expense_account
    elif root_type == "Income":
        credit_account = depreciation_expense_account
        debit_account = accumulated_depreciation_account
    else:
        frappe.throw(_("Depreciation Expense Account should be an Income or Expense Account."))

    return credit_account, debit_account

@frappe.whitelist()
def scrap_iat(iat_name):
    iat = frappe.get_doc("IaT", iat_name)

    if iat.docstatus != 1:
        frappe.throw(_("Iat {0} must be submitted").format(iat.name))
    elif iat.status in ("Cancelled", "Sold", "Scrapped"):
        frappe.throw(_("Iat {0} cannot be scrapped, as it is already {1}").format(iat.name, iat.status))

    depreciation_series = frappe.get_cached_value('Company',  iat.company,  "series_for_depreciation_entry")

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.naming_series = depreciation_series
    je.posting_date = today()
    je.company = iat.company
    je.remark = "Scrap Entry for iat {0}".format(iat_name)

    for entry in get_gl_entries_on_iat_disposal(iat):
        entry.update({
                "reference_type": "IaT",
                "reference_name": iat_name
        })
        je.append("accounts", entry)

    je.flags.ignore_permissions = True
    je.submit()

    frappe.db.set_value("IaT", iat_name, "disposal_date", today())
    frappe.db.set_value("IaT", iat_name, "journal_entry_for_scrap", je.name)
    iat.set_status("Scrapped")

    frappe.msgprint(_("Iat scrapped via Journal Entry {0}").format(je.name))

@frappe.whitelist()
def restore_iat(iat_name):
    iat = frappe.get_doc("IaT", iat_name)

    je = iat.journal_entry_for_scrap

    iat.db_set("disposal_date", None)
    iat.db_set("journal_entry_for_scrap", None)

    frappe.get_doc("Journal Entry", je).cancel()

    iat.set_status()

def get_gl_entries_on_iat_regain(iat, selling_amount=0, finance_book=None):
    iat_account, iat, depreciation_cost_center, accumulated_depr_account, accumulated_depr_amount, disposal_account, value_after_depreciation = \
            get_iat_details(iat, finance_book)

    gl_entries = [
            {
                    "account": iat_account,
                    "debit_in_account_currency": iat.gross_purchase_amount,
                    "debit": iat.gross_purchase_amount,
                    "cost_center": depreciation_cost_center
            },
            {
                    "account": accumulated_depr_account,
                    "credit_in_account_currency": accumulated_depr_amount,
                    "credit": accumulated_depr_amount,
                    "cost_center": depreciation_cost_center
            }
    ]

    profit_amount = abs(flt(value_after_depreciation)) - abs(flt(selling_amount))
    if profit_amount:
        get_profit_gl_entries(profit_amount, gl_entries, disposal_account, depreciation_cost_center)

    return gl_entries

def get_gl_entries_on_iat_disposal(iat, selling_amount=0, finance_book=None):
    iat_account, iat, depreciation_cost_center, accumulated_depr_account, accumulated_depr_amount, disposal_account, value_after_depreciation = \
            get_iat_details(iat, finance_book)

    gl_entries = [
            {
                    "account": iat_account,
                    "credit_in_account_currency": iat.gross_purchase_amount,
                    "credit": iat.gross_purchase_amount,
                    "cost_center": depreciation_cost_center
            },
            {
                    "account": accumulated_depr_account,
                    "debit_in_account_currency": accumulated_depr_amount,
                    "debit": accumulated_depr_amount,
                    "cost_center": depreciation_cost_center
            }
    ]

    profit_amount = flt(selling_amount) - flt(value_after_depreciation)
    if profit_amount:
        get_profit_gl_entries(profit_amount, gl_entries, disposal_account, depreciation_cost_center)

    return gl_entries

def get_iat_details(iat, finance_book=None):
    iat_account, accumulated_depr_account, depr_expense_account = get_depreciation_accounts(iat)
    disposal_account, depreciation_cost_center = get_disposal_account_and_cost_center(iat.company)
    depreciation_cost_center = iat.cost_center or depreciation_cost_center

    idx = 1
    if finance_book:
        for d in iat.finance_books:
            if d.finance_book == finance_book:
                idx = d.idx
                break

    value_after_depreciation = (iat.finance_books[idx - 1].value_after_depreciation
            if iat.calculate_depreciation else iat.value_after_depreciation)
    accumulated_depr_amount = flt(iat.gross_purchase_amount) - flt(value_after_depreciation)

    return iat_account, iat, depreciation_cost_center, accumulated_depr_account, accumulated_depr_amount, disposal_account, value_after_depreciation

def get_profit_gl_entries(profit_amount, gl_entries, disposal_account, depreciation_cost_center):
    debit_or_credit = "debit" if profit_amount < 0 else "credit"
    gl_entries.append({
            "account": disposal_account,
            "cost_center": depreciation_cost_center,
            debit_or_credit: abs(profit_amount),
            debit_or_credit + "_in_account_currency": abs(profit_amount)
    })

@frappe.whitelist()
def get_disposal_account_and_cost_center(company):
    disposal_account, depreciation_cost_center = frappe.get_cached_value('Company',  company,
            ["disposal_account", "depreciation_cost_center"])

    if not disposal_account:
        frappe.throw(_("Please set 'Gain/Loss Account on Iat Disposal' in Company {0}").format(company))
    if not depreciation_cost_center:
        frappe.throw(_("Please set 'Iat Depreciation Cost Center' in Company {0}").format(company))

    return disposal_account, depreciation_cost_center

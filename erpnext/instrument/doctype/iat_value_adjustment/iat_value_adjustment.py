# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, formatdate, getdate

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
        get_checks_for_pl_and_bs_accounts,
)
from erpnext.instrument.doctype.iat.iat import get_depreciation_amount
from erpnext.instrument.doctype.iat.depreciation import get_depreciation_accounts

from erpnext.regional.india.utils import (
        get_depreciation_amount as get_depreciation_amount_for_india,
)


class IaTValueAdjustment(Document):
    def validate(self):
        self.validate_date()
        self.set_current_iat_value()
        self.set_difference_amount()

    def on_submit(self):
        self.make_depreciation_entry()
        self.reschedule_depreciations(self.new_iat_value)

    def on_cancel(self):
        self.reschedule_depreciations(self.current_iat_value)

    def validate_date(self):
        iat_purchase_date = frappe.db.get_value('Instrument', self.iat, 'purchase_date')
        if getdate(self.date) < getdate(iat_purchase_date):
            frappe.throw(_("IaT Value Adjustment cannot be posted before IaT's purchase date <b>{0}</b>.")
                    .format(formatdate(iat_purchase_date)), title="Incorrect Date")

    def set_difference_amount(self):
        self.difference_amount = flt(self.current_iat_value - self.new_iat_value)

    def set_current_iat_value(self):
        if not self.current_iat_value and self.iat:
            self.current_iat_value = get_current_iat_value(self.iat, self.finance_book)

    def make_depreciation_entry(self):
        iat = frappe.get_doc("IaT", self.iat)
        iat_account, accumulated_depreciation_account, depreciation_expense_account = \
                get_depreciation_accounts(iat)

        depreciation_cost_center, depreciation_series = frappe.get_cached_value('Company',  iat.company,
                ["depreciation_cost_center", "series_for_depreciation_entry"])

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Depreciation Entry"
        je.naming_series = depreciation_series
        je.posting_date = self.date
        je.company = self.company
        je.remark = "Depreciation Entry against {0} worth {1}".format(self.iat, self.difference_amount)
        je.finance_book = self.finance_book

        credit_entry = {
                "account": accumulated_depreciation_account,
                "credit_in_account_currency": self.difference_amount,
                "cost_center": depreciation_cost_center or self.cost_center
        }

        debit_entry = {
                "account": depreciation_expense_account,
                "debit_in_account_currency": self.difference_amount,
                "cost_center": depreciation_cost_center or self.cost_center
        }

        accounting_dimensions = get_checks_for_pl_and_bs_accounts()

        for dimension in accounting_dimensions:
            if dimension.get('mandatory_for_bs'):
                credit_entry.update({
                        dimension['fieldname']: self.get(dimension['fieldname']) or dimension.get('default_dimension')
                })

            if dimension.get('mandatory_for_pl'):
                debit_entry.update({
                        dimension['fieldname']: self.get(dimension['fieldname']) or dimension.get('default_dimension')
                })

        je.append("accounts", credit_entry)
        je.append("accounts", debit_entry)

        je.flags.ignore_permissions = True
        je.submit()

        self.db_set("journal_entry", je.name)

    def reschedule_depreciations(self, iat_value):
        iat = frappe.get_doc('Instrument', self.iat)
        country = frappe.get_value('Company', self.company, 'country')

        for d in iat.finance_books:
            d.value_after_depreciation = iat_value

            if d.depreciation_method in ("Straight Line", "Manual"):
                end_date = max(s.schedule_date for s in iat.schedules if cint(s.finance_book_id) == d.idx)
                total_days = date_diff(end_date, self.date)
                rate_per_day = flt(d.value_after_depreciation) / flt(total_days)
                from_date = self.date
            else:
                no_of_depreciations = len([s.name for s in iat.schedules
                        if (cint(s.finance_book_id) == d.idx and not s.journal_entry)])

            value_after_depreciation = d.value_after_depreciation
            for data in iat.schedules:
                if cint(data.finance_book_id) == d.idx and not data.journal_entry:
                    if d.depreciation_method in ("Straight Line", "Manual"):
                        days = date_diff(data.schedule_date, from_date)
                        depreciation_amount = days * rate_per_day
                        from_date = data.schedule_date
                    else:
                        if country == "India":
                            depreciation_amount = get_depreciation_amount_for_india(iat, value_after_depreciation, d)
                        else:
                            depreciation_amount = get_depreciation_amount(iat, value_after_depreciation, d)

                    if depreciation_amount:
                        value_after_depreciation -= flt(depreciation_amount)
                        data.depreciation_amount = depreciation_amount

            d.db_update()

        iat.set_accumulated_depreciation(ignore_booked_entry=True)
        for iat_data in iat.schedules:
            if not iat_data.journal_entry:
                iat_data.db_update()

@frappe.whitelist()
def get_current_iat_value(iat, finance_book=None):
    cond = {'parent': iat, 'parenttype': 'IaT'}
    if finance_book:
        cond.update({'finance_book': finance_book})

    return frappe.db.get_value('Iat Finance Book', cond, 'value_after_depreciation')

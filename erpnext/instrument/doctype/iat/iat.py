# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

# Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
import math

import frappe
from frappe import _
from frappe.utils import (
        add_days,
        add_months,
        cint,
        date_diff,
        flt,
        get_datetime,
        get_last_day,
        getdate,
        month_diff,
        nowdate,
        today,
)
#test branch
import erpnext
from erpnext.accounts.general_ledger import make_reverse_gl_entries
from erpnext.instrument.doctype.iat.depreciation import (
        get_depreciation_accounts,
        get_disposal_account_and_cost_center,
)
from erpnext.instrument.doctype.tools_category.tools_category import get_tools_category_account
from erpnext.controllers.accounts_controller import AccountsController

class IaT(AccountsController):
    def validate(self):
        self.validate_iat_values()
        self.validate_iat_and_reference()
        self.validate_item()
        self.validate_cost_center()
        self.set_missing_values()
        if not self.split_from:
            self.prepare_depreciation_data()
        self.validate_gross_and_purchase_amount()
        if self.get("schedules"):
            self.validate_expected_value_after_useful_life()

        self.status = self.get_status()

    def on_submit(self):
        self.validate_in_use_date()
        self.set_status()
        self.make_iat_movement()
        if not self.booked_fixed_iat and self.validate_make_gl_entry():
            self.make_gl_entries()

    def on_cancel(self):
        self.validate_cancellation()
        self.cancel_movement_entries()
        self.delete_depreciation_entries()
        self.set_status()
        self.ignore_linked_doctypes = ('GL Entry', 'Stock Ledger Entry')
        make_reverse_gl_entries(voucher_type='IaT', voucher_no=self.name)
        self.db_set('booked_fixed_iat', 0)

    def validate_iat_and_reference(self):
        if self.purchase_invoice or self.purchase_receipt:
            reference_doc = 'Purchase Invoice' if self.purchase_invoice else 'Purchase Receipt'
            reference_name = self.purchase_invoice or self.purchase_receipt
            reference_doc = frappe.get_doc(reference_doc, reference_name)
            if reference_doc.get('company') != self.company:
                frappe.throw(_("Company of iat {0} and purchase document {1} doesn't matches.").format(self.name, reference_doc.get('name')))


        if self.is_existing_iat and self.purchase_invoice:
            frappe.throw(_("Purchase Invoice cannot be made against an existing iat {0}").format(self.name))

    def prepare_depreciation_data(self, date_of_sale=None, date_of_return=None):
        if self.calculate_depreciation:
            self.value_after_depreciation = 0
            self.set_depreciation_rate()
            self.make_depreciation_schedule(date_of_sale)
            self.set_accumulated_depreciation(date_of_sale, date_of_return)
        else:
            self.finance_books = []
            self.value_after_depreciation = (flt(self.gross_purchase_amount) -
                    flt(self.opening_accumulated_depreciation))

    def validate_item(self):
        item = frappe.get_cached_value("Item", self.item_code,
                ["is_fixed_asset", "is_stock_item", "disabled"], as_dict=1)
        if not item:
            frappe.throw(_("Item {0} does not exist").format(self.item_code))
        elif item.disabled:
            frappe.throw(_("Item {0} has been disabled").format(self.item_code))
        elif not item.is_fixed_asset:
            frappe.throw(_("Item {0} must be a Fixed IaT Item").format(self.item_code))
        # elif item.is_stock_item:
        # 	# frappe.throw(_("Item {0} must be a non-stock item").format(self.item_code))
        # 	# message box with green indicator warning
        # 	frappe.msgprint(_("Item {0} must be a non-stock item").format(self.item_code), indicator='green')


    def validate_cost_center(self):
        if not self.cost_center:
            return

        cost_center_company = frappe.db.get_value('Cost Center', self.cost_center, 'company')
        if cost_center_company != self.company:
            frappe.throw(
                    _("Selected Cost Center {} doesn't belongs to {}").format(
                            frappe.bold(self.cost_center),
                            frappe.bold(self.company)
                    ),
                    title=_("Invalid Cost Center")
            )

    def validate_in_use_date(self):
        if not self.available_for_use_date:
            frappe.throw(_("Available for use date is required"))

        for d in self.finance_books:
            if d.depreciation_start_date == self.available_for_use_date:
                frappe.throw(_("Row #{}: Depreciation Posting Date should not be equal to Available for Use Date.").format(d.idx),
                        title=_("Incorrect Date"))

    def set_missing_values(self):
        if not self.tools_category:
            self.tools_category = frappe.get_cached_value("Item", self.item_code, "tools_category")

        if self.item_code and not self.get('finance_books'):
            finance_books = get_item_details(self.item_code, self.tools_category)
            self.set('finance_books', finance_books)

    def validate_iat_values(self):
        if not self.tools_category:
            self.tools_category = frappe.get_cached_value("Item", self.item_code, "tools_category")

        if not flt(self.gross_purchase_amount):
            frappe.throw(_("Gross Purchase Amount is mandatory"), frappe.MandatoryError)

        if is_cwip_accounting_enabled(self.tools_category):
            if not self.is_existing_iat and not (self.purchase_receipt or self.purchase_invoice):
                frappe.throw(_("Please create purchase receipt or purchase invoice for the item {0}").
                        format(self.item_code))

            if (not self.purchase_receipt and self.purchase_invoice
                    and not frappe.db.get_value('Purchase Invoice', self.purchase_invoice, 'update_stock')):
                frappe.throw(_("Update stock must be enable for the purchase invoice {0}").
                        format(self.purchase_invoice))

        if not self.calculate_depreciation:
            return
        elif not self.finance_books:
            frappe.throw(_("Enter depreciation details"))

        if self.is_existing_iat:
            return

        if self.available_for_use_date and getdate(self.available_for_use_date) < getdate(self.purchase_date):
            frappe.throw(_("Available-for-use Date should be after purchase date"))

    def validate_gross_and_purchase_amount(self):
        if self.is_existing_iat:
            return

        if self.gross_purchase_amount and self.gross_purchase_amount != self.purchase_receipt_amount:
            error_message = _("Gross Purchase Amount should be <b>equal</b> to purchase amount of one single IaT.")
            error_message += "<br>"
            error_message += _("Please do not book expense of multiple iats against one single IaT.")
            frappe.throw(error_message, title=_("Invalid Gross Purchase Amount"))

    def make_iat_movement(self):
        reference_doctype = 'Purchase Receipt' if self.purchase_receipt else 'Purchase Invoice'
        reference_docname = self.purchase_receipt or self.purchase_invoice
        transaction_date = getdate(self.purchase_date)
        if reference_docname:
            posting_date, posting_time = frappe.db.get_value(reference_doctype, reference_docname, ["posting_date", "posting_time"])
            transaction_date = get_datetime("{} {}".format(posting_date, posting_time))
        iats = [{
                'iat': self.name,
                'iat_name': self.iat_name,
                'target_location': self.location,
                'to_employee': self.custodian
        }]
        iat_movement = frappe.get_doc({
                'doctype': 'IaT Movement',
                'iats': iats,
                'purpose': 'Receipt',
                'company': self.company,
                'transaction_date': transaction_date,
                'reference_doctype': reference_doctype,
                'reference_name': reference_docname
        }).insert()
        iat_movement.submit()

    def set_depreciation_rate(self):
        for d in self.get("finance_books"):
            d.rate_of_depreciation = flt(self.get_depreciation_rate(d, on_validate=True),
                    d.precision("rate_of_depreciation"))

    def make_depreciation_schedule(self, date_of_sale):
        if 'Manual' not in [d.depreciation_method for d in self.finance_books] and not self.get('schedules'):
            self.schedules = []

        if not self.available_for_use_date:
            return

        start = self.clear_depreciation_schedule()

        for finance_book in self.get('finance_books'):
            self._make_depreciation_schedule(finance_book, start, date_of_sale)

    def _make_depreciation_schedule(self, finance_book, start, date_of_sale):
        self.validate_iat_finance_books(finance_book)

        value_after_depreciation = self._get_value_after_depreciation(finance_book)
        finance_book.value_after_depreciation = value_after_depreciation

        number_of_pending_depreciations = cint(finance_book.total_number_of_depreciations) - \
                cint(self.number_of_depreciations_booked)

        has_pro_rata = self.check_is_pro_rata(finance_book)
        if has_pro_rata:
            number_of_pending_depreciations += 1

        skip_row = False

        for n in range(start[finance_book.idx-1], number_of_pending_depreciations):
            # If depreciation is already completed (for double declining balance)
            if skip_row:
                continue

            depreciation_amount = get_depreciation_amount(self, value_after_depreciation, finance_book)

            if not has_pro_rata or n < cint(number_of_pending_depreciations) - 1:
                schedule_date = add_months(finance_book.depreciation_start_date,
                        n * cint(finance_book.frequency_of_depreciation))

                # schedule date will be a year later from start date
                # so monthly schedule date is calculated by removing 11 months from it
                monthly_schedule_date = add_months(schedule_date, - finance_book.frequency_of_depreciation + 1)

            # if iat is being sold
            if date_of_sale:
                from_date = self.get_from_date(finance_book.finance_book)
                depreciation_amount, days, months = self.get_pro_rata_amt(finance_book, depreciation_amount,
                        from_date, date_of_sale)

                if depreciation_amount > 0:
                    self._add_depreciation_row(date_of_sale, depreciation_amount, finance_book.depreciation_method,
                            finance_book.finance_book, finance_book.idx)

                break

            # For first row
            if has_pro_rata and not self.opening_accumulated_depreciation and n==0:
                from_date = add_days(self.available_for_use_date, -1) # needed to calc depr amount for available_for_use_date too
                depreciation_amount, days, months = self.get_pro_rata_amt(finance_book, depreciation_amount,
                        from_date, finance_book.depreciation_start_date)

                # For first depr schedule date will be the start date
                # so monthly schedule date is calculated by removing month difference between use date and start date
                monthly_schedule_date = add_months(finance_book.depreciation_start_date, - months + 1)

            # For last row
            elif has_pro_rata and n == cint(number_of_pending_depreciations) - 1:
                if not self.flags.increase_in_iat_life:
                    # In case of increase_in_iat_life, the self.to_date is already set on iat_repair submission
                    self.to_date = add_months(self.available_for_use_date,
                            (n + self.number_of_depreciations_booked) * cint(finance_book.frequency_of_depreciation))

                depreciation_amount_without_pro_rata = depreciation_amount

                depreciation_amount, days, months = self.get_pro_rata_amt(finance_book,
                        depreciation_amount, schedule_date, self.to_date)

                depreciation_amount = self.get_adjusted_depreciation_amount(depreciation_amount_without_pro_rata,
                        depreciation_amount, finance_book.finance_book)

                monthly_schedule_date = add_months(schedule_date, 1)
                schedule_date = add_days(schedule_date, days)
                last_schedule_date = schedule_date

            if not depreciation_amount:
                continue
            value_after_depreciation -= flt(depreciation_amount,
                    self.precision("gross_purchase_amount"))

            # Adjust depreciation amount in the last period based on the expected value after useful life
            if finance_book.expected_value_after_useful_life and ((n == cint(number_of_pending_depreciations) - 1
                    and value_after_depreciation != finance_book.expected_value_after_useful_life)
                    or value_after_depreciation < finance_book.expected_value_after_useful_life):
                depreciation_amount += (value_after_depreciation - finance_book.expected_value_after_useful_life)
                skip_row = True

            if depreciation_amount > 0:
                # With monthly depreciation, each depreciation is divided by months remaining until next date
                if self.allow_monthly_depreciation:
                    # month range is 1 to 12
                    # In pro rata case, for first and last depreciation, month range would be different
                    month_range = months \
                            if (has_pro_rata and n==0) or (has_pro_rata and n == cint(number_of_pending_depreciations) - 1) \
                            else finance_book.frequency_of_depreciation

                    for r in range(month_range):
                        if (has_pro_rata and n == 0):
                            # For first entry of monthly depr
                            if r == 0:
                                days_until_first_depr = date_diff(monthly_schedule_date, self.available_for_use_date)
                                per_day_amt = depreciation_amount / days
                                depreciation_amount_for_current_month = per_day_amt * days_until_first_depr
                                depreciation_amount -= depreciation_amount_for_current_month
                                date = monthly_schedule_date
                                amount = depreciation_amount_for_current_month
                            else:
                                date = add_months(monthly_schedule_date, r)
                                amount = depreciation_amount / (month_range - 1)
                        elif (has_pro_rata and n == cint(number_of_pending_depreciations) - 1) and r == cint(month_range) - 1:
                            # For last entry of monthly depr
                            date = last_schedule_date
                            amount = depreciation_amount / month_range
                        else:
                            date = add_months(monthly_schedule_date, r)
                            amount = depreciation_amount / month_range

                        self._add_depreciation_row(date, amount, finance_book.depreciation_method,
                                finance_book.finance_book, finance_book.idx)
                else:
                    self._add_depreciation_row(schedule_date, depreciation_amount, finance_book.depreciation_method,
                            finance_book.finance_book, finance_book.idx)

    def _add_depreciation_row(self, schedule_date, depreciation_amount, depreciation_method, finance_book, finance_book_id):
        self.append("schedules", {
                "schedule_date": schedule_date,
                "depreciation_amount": depreciation_amount,
                "depreciation_method": depreciation_method,
                "finance_book": finance_book,
                "finance_book_id": finance_book_id
        })

    def _get_value_after_depreciation(self, finance_book):
        # value_after_depreciation - current IaT value
        if self.docstatus == 1 and finance_book.value_after_depreciation:
            value_after_depreciation = flt(finance_book.value_after_depreciation)
        else:
            value_after_depreciation = (flt(self.gross_purchase_amount) -
                    flt(self.opening_accumulated_depreciation))

        return value_after_depreciation

    # depreciation schedules need to be cleared before modification due to increase in iat life/iat sales
    # JE: Journal Entry, FB: Finance Book
    def clear_depreciation_schedule(self):
        start = []
        num_of_depreciations_completed = 0
        depr_schedule = []

        for schedule in self.get('schedules'):
            # to update start when there are JEs linked with all the schedule rows corresponding to an FB
            if len(start) == (int(schedule.finance_book_id) - 2):
                start.append(num_of_depreciations_completed)
                num_of_depreciations_completed = 0

            # to ensure that start will only be updated once for each FB
            if len(start) == (int(schedule.finance_book_id) - 1):
                if schedule.journal_entry:
                    num_of_depreciations_completed += 1
                    depr_schedule.append(schedule)
                else:
                    start.append(num_of_depreciations_completed)
                    num_of_depreciations_completed = 0

        # to update start when all the schedule rows corresponding to the last FB are linked with JEs
        if len(start) == (len(self.finance_books) - 1):
            start.append(num_of_depreciations_completed)

        # when the Depreciation Schedule is being created for the first time
        if start == []:
            start = [0] * len(self.finance_books)
        else:
            self.schedules = depr_schedule

        return start

    def get_from_date(self, finance_book):
        if not self.get('schedules'):
            return self.available_for_use_date

        if len(self.finance_books) == 1:
            return self.schedules[-1].schedule_date

        from_date = ""
        for schedule in self.get('schedules'):
            if schedule.finance_book == finance_book:
                from_date = schedule.schedule_date

        if from_date:
            return from_date

        # since depr for available_for_use_date is not yet booked
        return add_days(self.available_for_use_date, -1)

    # if it returns True, depreciation_amount will not be equal for the first and last rows
    def check_is_pro_rata(self, row):
        has_pro_rata = False

        # if not existing iat, from_date = available_for_use_date
        # otherwise, if number_of_depreciations_booked = 2, available_for_use_date = 01/01/2020 and frequency_of_depreciation = 12
        # from_date = 01/01/2022
        from_date = self.get_modified_available_for_use_date(row)
        days = date_diff(row.depreciation_start_date, from_date) + 1

        # if frequency_of_depreciation is 12 months, total_days = 365
        total_days = get_total_days(row.depreciation_start_date, row.frequency_of_depreciation)

        if days < total_days:
            has_pro_rata = True

        return has_pro_rata

    def get_modified_available_for_use_date(self, row):
        return add_months(self.available_for_use_date, (self.number_of_depreciations_booked * row.frequency_of_depreciation))

    def validate_iat_finance_books(self, row):
        if flt(row.expected_value_after_useful_life) >= flt(self.gross_purchase_amount):
            frappe.throw(_("Row {0}: Expected Value After Useful Life must be less than Gross Purchase Amount")
                    .format(row.idx))

        if not row.depreciation_start_date:
            if not self.available_for_use_date:
                frappe.throw(_("Row {0}: Depreciation Start Date is required").format(row.idx))
            row.depreciation_start_date = get_last_day(self.available_for_use_date)

        if not self.is_existing_iat:
            self.opening_accumulated_depreciation = 0
            self.number_of_depreciations_booked = 0
        else:
            depreciable_amount = flt(self.gross_purchase_amount) - flt(row.expected_value_after_useful_life)
            if flt(self.opening_accumulated_depreciation) > depreciable_amount:
                frappe.throw(_("Opening Accumulated Depreciation must be less than equal to {0}")
                        .format(depreciable_amount))

            if self.opening_accumulated_depreciation:
                if not self.number_of_depreciations_booked:
                    frappe.throw(_("Please set Number of Depreciations Booked"))
            else:
                self.number_of_depreciations_booked = 0

            if cint(self.number_of_depreciations_booked) > cint(row.total_number_of_depreciations):
                frappe.throw(_("Number of Depreciations Booked cannot be greater than Total Number of Depreciations"))

        if row.depreciation_start_date and getdate(row.depreciation_start_date) < getdate(self.purchase_date):
            frappe.throw(_("Depreciation Row {0}: Next Depreciation Date cannot be before Purchase Date")
                    .format(row.idx))

        if row.depreciation_start_date and getdate(row.depreciation_start_date) < getdate(self.available_for_use_date):
            frappe.throw(_("Depreciation Row {0}: Next Depreciation Date cannot be before Available-for-use Date")
                    .format(row.idx))

    # to ensure that final accumulated depreciation amount is accurate
    def get_adjusted_depreciation_amount(self, depreciation_amount_without_pro_rata, depreciation_amount_for_last_row, finance_book):
        if not self.opening_accumulated_depreciation:
            depreciation_amount_for_first_row = self.get_depreciation_amount_for_first_row(finance_book)

            if depreciation_amount_for_first_row + depreciation_amount_for_last_row != depreciation_amount_without_pro_rata:
                depreciation_amount_for_last_row = depreciation_amount_without_pro_rata - depreciation_amount_for_first_row

        return depreciation_amount_for_last_row

    def get_depreciation_amount_for_first_row(self, finance_book):
        if self.has_only_one_finance_book():
            return self.schedules[0].depreciation_amount
        else:
            for schedule in self.schedules:
                if schedule.finance_book == finance_book:
                    return schedule.depreciation_amount

    def has_only_one_finance_book(self):
        if len(self.finance_books) == 1:
            return True

    def set_accumulated_depreciation(self, date_of_sale=None, date_of_return=None, ignore_booked_entry = False):
        straight_line_idx = [d.idx for d in self.get("schedules") if d.depreciation_method == 'Straight Line']
        finance_books = []

        for i, d in enumerate(self.get("schedules")):
            if ignore_booked_entry and d.journal_entry:
                continue

            if int(d.finance_book_id) not in finance_books:
                accumulated_depreciation = flt(self.opening_accumulated_depreciation)
                value_after_depreciation = flt(self.get_value_after_depreciation(d.finance_book_id))
                finance_books.append(int(d.finance_book_id))

            depreciation_amount = flt(d.depreciation_amount, d.precision("depreciation_amount"))
            value_after_depreciation -= flt(depreciation_amount)

            # for the last row, if depreciation method = Straight Line
            if straight_line_idx and i == max(straight_line_idx) - 1 and not date_of_sale and not date_of_return:
                book = self.get('finance_books')[cint(d.finance_book_id) - 1]
                depreciation_amount += flt(value_after_depreciation -
                        flt(book.expected_value_after_useful_life), d.precision("depreciation_amount"))

            d.depreciation_amount = depreciation_amount
            accumulated_depreciation += d.depreciation_amount
            d.accumulated_depreciation_amount = flt(accumulated_depreciation,
                    d.precision("accumulated_depreciation_amount"))

    def get_value_after_depreciation(self, idx):
        return flt(self.get('finance_books')[cint(idx)-1].value_after_depreciation)

    def validate_expected_value_after_useful_life(self):
        for row in self.get('finance_books'):
            accumulated_depreciation_after_full_schedule = [d.accumulated_depreciation_amount
                    for d in self.get("schedules") if cint(d.finance_book_id) == row.idx]

            if accumulated_depreciation_after_full_schedule:
                accumulated_depreciation_after_full_schedule = max(accumulated_depreciation_after_full_schedule)

                iat_value_after_full_schedule = flt(
                        flt(self.gross_purchase_amount) -
                        flt(accumulated_depreciation_after_full_schedule), self.precision('gross_purchase_amount'))

                if (row.expected_value_after_useful_life and
                        row.expected_value_after_useful_life < iat_value_after_full_schedule):
                    frappe.throw(_("Depreciation Row {0}: Expected value after useful life must be greater than or equal to {1}")
                            .format(row.idx, iat_value_after_full_schedule))
                elif not row.expected_value_after_useful_life:
                    row.expected_value_after_useful_life = iat_value_after_full_schedule

    def validate_cancellation(self):
        if self.status in ("In Maintenance", "Out of Order"):
            frappe.throw(_("There are active maintenance or repairs against the iat. You must complete all of them before cancelling the iat."))
        if self.status not in ("Submitted", "Partially Depreciated", "Fully Depreciated"):
            frappe.throw(_("IaT cannot be cancelled, as it is already {0}").format(self.status))

    def cancel_movement_entries(self):
        movements = frappe.db.sql(
                """SELECT asm.name, asm.docstatus
			FROM `tabIaT Movement` asm, `tabIaT Movement Item` asm_item
			WHERE asm_item.parent=asm.name and asm_item.iat=%s and asm.docstatus=1""", self.name, as_dict=1)

        for movement in movements:
            movement = frappe.get_doc('IaT Movement', movement.get('name'))
            movement.cancel()

    def delete_depreciation_entries(self):
        for d in self.get("schedules"):
            if d.journal_entry:
                frappe.get_doc("Journal Entry", d.journal_entry).cancel()
                d.db_set("journal_entry", None)

        self.db_set("value_after_depreciation",
                (flt(self.gross_purchase_amount) - flt(self.opening_accumulated_depreciation)))

    def set_status(self, status=None):
        '''Get and update status'''
        if not status:
            status = self.get_status()
        self.db_set("status", status)

    def get_status(self):
        '''Returns status based on whether it is draft, submitted, scrapped or depreciated'''
        if self.docstatus == 0:
            status = "Draft"
        elif self.docstatus == 1:
            status = "Submitted"

            if self.journal_entry_for_scrap:
                status = "Scrapped"
            elif self.finance_books:
                idx = self.get_default_finance_book_idx() or 0

                expected_value_after_useful_life = self.finance_books[idx].expected_value_after_useful_life
                value_after_depreciation = self.finance_books[idx].value_after_depreciation

                if flt(value_after_depreciation) <= expected_value_after_useful_life:
                    status = "Fully Depreciated"
                elif flt(value_after_depreciation) < flt(self.gross_purchase_amount):
                    status = 'Partially Depreciated'
        elif self.docstatus == 2:
            status = "Cancelled"
        return status

    def get_default_finance_book_idx(self):
        if not self.get('default_finance_book') and self.company:
            self.default_finance_book = erpnext.get_default_finance_book(self.company)

        if self.get('default_finance_book'):
            for d in self.get('finance_books'):
                if d.finance_book == self.default_finance_book:
                    return cint(d.idx) - 1

    def validate_make_gl_entry(self):
        purchase_document = self.get_purchase_document()
        if not purchase_document:
            return False

        iat_bought_with_invoice = (purchase_document == self.purchase_invoice)
        iat_account = self.get_fixed_iat_account()

        cwip_enabled = is_cwip_accounting_enabled(self.tools_category)
        cwip_account = self.get_cwip_account(cwip_enabled=cwip_enabled)

        query = """SELECT name FROM `tabGL Entry` WHERE voucher_no = %s and account = %s"""
        if iat_bought_with_invoice:
            # with invoice purchase either expense or cwip has been booked
            expense_booked = frappe.db.sql(query, (purchase_document, iat_account), as_dict=1)
            if expense_booked:
                # if expense is already booked from invoice then do not make gl entries regardless of cwip enabled/disabled
                return False

            cwip_booked = frappe.db.sql(query, (purchase_document, cwip_account), as_dict=1)
            if cwip_booked:
                # if cwip is booked from invoice then make gl entries regardless of cwip enabled/disabled
                return True
        else:
            # with receipt purchase either cwip has been booked or no entries have been made
            if not cwip_account:
                # if cwip account isn't available do not make gl entries
                return False

            cwip_booked = frappe.db.sql(query, (purchase_document, cwip_account), as_dict=1)
            # if cwip is not booked from receipt then do not make gl entries
            # if cwip is booked from receipt then make gl entries
            return cwip_booked

    def get_purchase_document(self):
        iat_bought_with_invoice = self.purchase_invoice and frappe.db.get_value('Purchase Invoice', self.purchase_invoice, 'update_stock')
        purchase_document = self.purchase_invoice if iat_bought_with_invoice else self.purchase_receipt

        return purchase_document

    def get_fixed_iat_account(self):
        iat_account = get_tools_category_account('iat_account', None, self.name, None, self.tools_category, self.company)
        if not iat_account:
            frappe.throw(
                    _("Set {0} in tools category {1} for company {2}").format(
                            frappe.bold("IaT Account"),
                            frappe.bold(self.tools_category),
                            frappe.bold(self.company),
                    ),
                    title=_("Account not Found"),
            )
        return iat_account

    def get_cwip_account(self, cwip_enabled=False):
        cwip_account = None
        try:
            cwip_account = get_iat_account("capital_work_in_progress_account", self.name, self.tools_category, self.company)
        except Exception:
            # if no cwip account found in category or company and "cwip is enabled" then raise else silently pass
            if cwip_enabled:
                raise

        return cwip_account

    def make_gl_entries(self):
        gl_entries = []

        purchase_document = self.get_purchase_document()
        iat_account, cwip_account = self.get_fixed_iat_account(), self.get_cwip_account()

        if (purchase_document and self.purchase_receipt_amount and self.available_for_use_date <= nowdate()):

            gl_entries.append(self.get_gl_dict({
                    "account": cwip_account,
                    "against": iat_account,
                    "remarks": self.get("remarks") or _("Accounting Entry for IaT"),
                    "posting_date": self.available_for_use_date,
                    "credit": self.purchase_receipt_amount,
                    "credit_in_account_currency": self.purchase_receipt_amount,
                    "cost_center": self.cost_center
            }, item=self))

            gl_entries.append(self.get_gl_dict({
                    "account": iat_account,
                    "against": cwip_account,
                    "remarks": self.get("remarks") or _("Accounting Entry for IaT"),
                    "posting_date": self.available_for_use_date,
                    "debit": self.purchase_receipt_amount,
                    "debit_in_account_currency": self.purchase_receipt_amount,
                    "cost_center": self.cost_center
            }, item=self))

        if gl_entries:
            from erpnext.accounts.general_ledger import make_gl_entries

            make_gl_entries(gl_entries)
            self.db_set('booked_fixed_iat', 1)

    @frappe.whitelist()
    def get_depreciation_rate(self, args, on_validate=False):
        if isinstance(args, str):
            args = json.loads(args)

        float_precision = cint(frappe.db.get_default("float_precision")) or 2

        if args.get("depreciation_method") == 'Double Declining Balance':
            return 200.0 / args.get("total_number_of_depreciations")

        if args.get("depreciation_method") == "Written Down Value":
            if args.get("rate_of_depreciation") and on_validate:
                return args.get("rate_of_depreciation")

            no_of_years = flt(args.get("total_number_of_depreciations") * flt(args.get("frequency_of_depreciation"))) / 12
            value = flt(args.get("expected_value_after_useful_life")) / flt(self.gross_purchase_amount)

            # square root of flt(salvage_value) / flt(iat_cost)
            depreciation_rate = math.pow(value, 1.0/flt(no_of_years, 2))

            return 100 * (1 - flt(depreciation_rate, float_precision))

    def get_pro_rata_amt(self, row, depreciation_amount, from_date, to_date):
        days = date_diff(to_date, from_date)
        months = month_diff(to_date, from_date)
        total_days = get_total_days(to_date, row.frequency_of_depreciation)

        return (depreciation_amount * flt(days)) / flt(total_days), days, months

def update_maintenance_status():
    iats = frappe.get_all(
            "IaT", filters={"docstatus": 1, "maintenance_required": 1}
    )

    for iat in iats:
        iat = frappe.get_doc("IaT", iat.name)
        if frappe.db.exists("IaT Repair", {"iat_name": iat.name, "repair_status": "Pending"}):
            iat.set_status("Out of Order")
        elif frappe.db.exists("IaT Maintenance Task", {"parent": iat.name, "next_due_date": today()}):
            iat.set_status("In Maintenance")
        else:
            iat.set_status()

def make_post_gl_entry():

    iat_categories = frappe.db.get_all('Tools Category', fields = ['name', 'enable_cwip_accounting'])

    for tools_category in iat_categories:
        if cint(tools_category.enable_cwip_accounting):
            iats = frappe.db.sql_list(""" select name from `tabIaT`
				where tools_category = %s and ifnull(booked_fixed_iat, 0) = 0
				and available_for_use_date = %s""", (tools_category.name, nowdate()))

            for iat in iats:
                doc = frappe.get_doc('IaT', iat)
                doc.make_gl_entries()

def get_iat_naming_series():
    meta = frappe.get_meta('IaT')
    return meta.get_field("naming_series").options

@frappe.whitelist()
def make_sales_invoice(iat, item_code, company, serial_no=None):
    si = frappe.new_doc("Sales Invoice")
    si.company = company
    si.currency = frappe.get_cached_value('Company',  company,  "default_currency")
    disposal_account, depreciation_cost_center = get_disposal_account_and_cost_center(company)
    si.append("items", {
            "item_code": item_code,
            "is_fixed_asset": 1,
            "iat": iat,
            "income_account": disposal_account,
            "serial_no": serial_no,
            "cost_center": depreciation_cost_center,
            "qty": 1
    })
    si.set_missing_values()
    return si

@frappe.whitelist()
def create_iat_maintenance(iat, item_code, item_name, tools_category, company):
    iat_maintenance = frappe.new_doc("IaT Maintenance")
    iat_maintenance.update({
            "iat_name": iat,
            "company": company,
            "item_code": item_code,
            "item_name": item_name,
            "tools_category": tools_category
    })
    return iat_maintenance

@frappe.whitelist()
def create_iat_repair(iat, iat_name):
    iat_repair = frappe.new_doc("IaT Repair")
    iat_repair.update({
            "iat": iat,
            "iat_name": iat_name
    })
    return iat_repair

@frappe.whitelist()
def create_iat_value_adjustment(iat, tools_category, company):
    iat_value_adjustment = frappe.new_doc("Iat Value Adjustment")
    iat_value_adjustment.update({
            "iat": iat,
            "company": company,
            "tools_category": tools_category
    })
    return iat_value_adjustment


#Day la ban Tan fix
@frappe.whitelist()
def transfer_iat(args):
    args = json.loads(args)

    if args.get('serial_no'):
        args['quantity'] = len(args.get('serial_no').split('\n'))

    movement_entry = frappe.new_doc("IaT Movement")
    movement_entry.update(args)
    movement_entry.insert()
    movement_entry.submit()

    frappe.db.commit()

    frappe.msgprint(_("IaT Movement record {0} created").format("<a href='/app/Form/IaT Movement/{0}'>{0}</a>").format(movement_entry.name))

@frappe.whitelist()
def get_item_details(item_code, tools_category):
    tools_category_doc = frappe.get_doc('Tools Category', tools_category)
    books = []
    for d in tools_category_doc.finance_books:
        books.append({
                'finance_book': d.finance_book,
                'depreciation_method': d.depreciation_method,
                'total_number_of_depreciations': d.total_number_of_depreciations,
                'frequency_of_depreciation': d.frequency_of_depreciation,
                'start_date': nowdate()
        })

    return books

def get_iat_account(account_name, iat=None, tools_category=None, company=None):
    account = None
    if iat:
        account = get_tools_category_account(account_name, iat=iat,
                        tools_category = tools_category, company = company)

    if not iat and not account:
        account = get_tools_category_account(account_name, tools_category = tools_category, company = company)

    if not account:
        account = frappe.get_cached_value('Company',  company,  account_name)

    if not account:
        if not tools_category:
            frappe.throw(_("Set {0} in company {1}").format(account_name.replace('_', ' ').title(), company))
        else:
            frappe.throw(_("Set {0} in tools category {1} or company {2}")
                    .format(account_name.replace('_', ' ').title(), tools_category, company))

    return account

@frappe.whitelist()
def make_journal_entry(iat_name):
    iat = frappe.get_doc("IaT", iat_name)
    iat_account, accumulated_depreciation_account, depreciation_expense_account = \
            get_depreciation_accounts(iat)

    depreciation_cost_center, depreciation_series = frappe.db.get_value("Company", iat.company,
            ["depreciation_cost_center", "series_for_depreciation_entry"])
    depreciation_cost_center = iat.cost_center or depreciation_cost_center

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Depreciation Entry"
    je.naming_series = depreciation_series
    je.company = iat.company
    je.remark = "Depreciation Entry against iat {0}".format(iat_name)

    je.append("accounts", {
            "account": depreciation_expense_account,
            "reference_type": "IaT",
            "reference_name": iat.name,
            "cost_center": depreciation_cost_center
    })

    je.append("accounts", {
            "account": accumulated_depreciation_account,
            "reference_type": "IaT",
            "reference_name": iat.name
    })

    return je

@frappe.whitelist()
def make_iat_movement(iats, purpose=None):
    import json

    if isinstance(iats, str):
        iats = json.loads(iats)

    if len(iats) == 0:
        frappe.throw(_('Atleast one iat has to be selected.'))

    iat_movement = frappe.new_doc("IaT Movement")
    iat_movement.quantity = len(iats)
    for iat in iats:
        iat = frappe.get_doc('IaT', iat.get('name'))
        iat_movement.company = iat.get('company')
        iat_movement.append("iats", {
                'iat': iat.get('name'),
                'source_location': iat.get('location'),
                'from_employee': iat.get('custodian')
        })

    if iat_movement.get('iats'):
        return iat_movement.as_dict()

def is_cwip_accounting_enabled(tools_category):
    return cint(frappe.db.get_value("Tools Category", tools_category, "enable_cwip_accounting"))

def get_total_days(date, frequency):
    period_start_date = add_months(date,
            cint(frequency) * -1)

    return date_diff(date, period_start_date)

@erpnext.allow_regional
def get_depreciation_amount(iat, depreciable_value, row):
    if row.depreciation_method in ("Straight Line", "Manual"):
        # if the Depreciation Schedule is being prepared for the first time
        if not iat.flags.increase_in_iat_life:
            depreciation_amount = (flt(iat.gross_purchase_amount) -
                    flt(row.expected_value_after_useful_life)) / flt(row.total_number_of_depreciations)

        # if the Depreciation Schedule is being modified after IaT Repair
        else:
            depreciation_amount = (flt(row.value_after_depreciation) -
                    flt(row.expected_value_after_useful_life)) / (date_diff(iat.to_date, iat.available_for_use_date) / 365)
    else:
        depreciation_amount = flt(depreciable_value * (flt(row.rate_of_depreciation) / 100))

    return depreciation_amount

@frappe.whitelist()
def split_iat(iat_name, split_qty):
    iat = frappe.get_doc("IaT", iat_name)
    split_qty = cint(split_qty)

    if split_qty >= iat.iat_quantity:
        frappe.throw(_("Split qty cannot be grater than or equal to iat qty"))

    remaining_qty = iat.iat_quantity - split_qty

    new_iat = create_new_iat_after_split(iat, split_qty)
    update_existing_iat(iat, remaining_qty)

    return new_iat

def update_existing_iat(iat, remaining_qty):
    remaining_gross_purchase_amount = flt((iat.gross_purchase_amount * remaining_qty) / iat.iat_quantity)
    opening_accumulated_depreciation = flt((iat.opening_accumulated_depreciation * remaining_qty) / iat.iat_quantity)

    frappe.db.set_value("IaT", iat.name, {
            'opening_accumulated_depreciation': opening_accumulated_depreciation,
            'gross_purchase_amount': remaining_gross_purchase_amount,
            'iat_quantity': remaining_qty
    })

    for finance_book in iat.get('finance_books'):
        value_after_depreciation = flt((finance_book.value_after_depreciation * remaining_qty)/iat.iat_quantity)
        expected_value_after_useful_life = flt((finance_book.expected_value_after_useful_life * remaining_qty)/iat.iat_quantity)
        frappe.db.set_value('IaT Finance Book', finance_book.name, 'value_after_depreciation', value_after_depreciation)
        frappe.db.set_value('IaT Finance Book', finance_book.name, 'expected_value_after_useful_life', expected_value_after_useful_life)

    accumulated_depreciation = 0

    for term in iat.get('schedules'):
        depreciation_amount = flt((term.depreciation_amount * remaining_qty)/iat.iat_quantity)
        frappe.db.set_value('Depreciation Schedule', term.name, 'depreciation_amount', depreciation_amount)
        accumulated_depreciation += depreciation_amount
        frappe.db.set_value('Depreciation Schedule', term.name, 'accumulated_depreciation_amount', accumulated_depreciation)

def create_new_iat_after_split(iat, split_qty):
    new_iat = frappe.copy_doc(iat)
    new_gross_purchase_amount = flt((iat.gross_purchase_amount * split_qty) / iat.iat_quantity)
    opening_accumulated_depreciation = flt((iat.opening_accumulated_depreciation * split_qty) / iat.iat_quantity)

    new_iat.gross_purchase_amount = new_gross_purchase_amount
    new_iat.opening_accumulated_depreciation = opening_accumulated_depreciation
    new_iat.iat_quantity = split_qty
    new_iat.split_from = iat.name
    accumulated_depreciation = 0

    for finance_book in new_iat.get('finance_books'):
        finance_book.value_after_depreciation = flt((finance_book.value_after_depreciation * split_qty)/iat.iat_quantity)
        finance_book.expected_value_after_useful_life = flt((finance_book.expected_value_after_useful_life * split_qty)/iat.iat_quantity)

    for term in new_iat.get('schedules'):
        depreciation_amount = flt((term.depreciation_amount * split_qty)/iat.iat_quantity)
        term.depreciation_amount = depreciation_amount
        accumulated_depreciation += depreciation_amount
        term.accumulated_depreciation_amount = accumulated_depreciation

    new_iat.submit()
    new_iat.set_status()

    for term in new_iat.get('schedules'):
        # Update references in JV
        if term.journal_entry:
            add_reference_in_jv_on_split(term.journal_entry, new_iat.name, iat.name, term.depreciation_amount)

    return new_iat

def add_reference_in_jv_on_split(entry_name, new_iat_name, old_iat_name, depreciation_amount):
    journal_entry = frappe.get_doc('Journal Entry', entry_name)
    entries_to_add = []
    idx = len(journal_entry.get('accounts')) + 1

    for account in journal_entry.get('accounts'):
        if account.reference_name == old_iat_name:
            entries_to_add.append(frappe.copy_doc(account).as_dict())
            if account.credit:
                account.credit = account.credit - depreciation_amount
                account.credit_in_account_currency = account.credit_in_account_currency - \
                        account.exchange_rate * depreciation_amount
            elif account.debit:
                account.debit = account.debit - depreciation_amount
                account.debit_in_account_currency = account.debit_in_account_currency - \
                        account.exchange_rate * depreciation_amount

    for entry in entries_to_add:
        entry.reference_name = new_iat_name
        if entry.credit:
            entry.credit = depreciation_amount
            entry.credit_in_account_currency = entry.exchange_rate * depreciation_amount
        elif entry.debit:
            entry.debit = depreciation_amount
            entry.debit_in_account_currency = entry.exchange_rate * depreciation_amount

        entry.idx = idx
        idx += 1

        journal_entry.append('accounts', entry)

    journal_entry.flags.ignore_validate_update_after_submit = True
    journal_entry.save()

    # Repost GL Entries
    journal_entry.docstatus = 2
    journal_entry.make_gl_entries(1)
    journal_entry.docstatus = 1
    journal_entry.make_gl_entries()

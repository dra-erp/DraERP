# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.report.can_doi_ke_toan import (
	get_columns,
	get_data,
	get_period_list,
)


def execute(filters=None):
	period_list = get_period_list(filters.from_fiscal_year, filters.to_fiscal_year,
		filters.period_start_date, filters.period_end_date, filters.filter_based_on, filters.periodicity,
		company=filters.company)

	income = get_data(period_list,filters.company,filters.finance_book,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True, ignore_accumulated_values_for_fy= True)

	data = []
	data.extend(income or [])

	columns = get_columns(filters.periodicity, period_list, filters.accumulated_values, filters.company)
	return columns, data, None, None, None

# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _

from erpnext.stock.utils import (
	is_reposting_item_valuation_in_progress,
)
from pymysql import NULL


def execute(filters=None):
	is_reposting_item_valuation_in_progress()
	items = get_items(filters)
	sl_entries = get_stock_ledger_entries(items)
	item_details = get_item_details(items, sl_entries)
	columns = get_columns(item_details[sl_entries[0].item_code].stock_uom)

	data = []
	total_in = 0
	total_out = 0
	for sle in sl_entries:
		item_detail = item_details[sle.item_code]

		sle.update(item_detail)

		if max(sle.actual_qty, 0) != 0:
			total_in += sle.actual_qty
			sle.update({
				"in_qty": sle.actual_qty,
				"in_id": sle.ID
			})
		else:
			total_out += sle.actual_qty
			sle.update({
				"out_qty": sle.actual_qty,
				"out_id": sle.ID
			})

		data.append(sle)
	total = {
		"voucher_type": "Total",
		"in_qty": total_in,
		"out_qty": total_out,
		"qty_after_transaction": sl_entries[-1].qty_after_transaction,
	}
	data.append(total)

	return columns, data


def get_columns(uom):
	columns = [
		{"label": _("Creation"), "fieldname": "creation", "fieldtype": "Datetime", "width": 150},
		{"label": _("In ID"), "fieldname": "in_id", "fieldtype": "Link", "options": "Stock Ledger Entry", "width": 150},
		{"label": _("Out ID"), "fieldname": "out_id", "fieldtype": "Link", "options": "Stock Ledger Entry", "width": 150},
		{"label": _("Description"), "fieldname": "voucher_type", "width": 110},
		{"label": _("UOM"), "fieldname": "stock_uom", "width": 110},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Datetime", "width": 150},
		{"label": _("In Qty(per {})".format(uom)), "fieldname": "in_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Out Qty(per {})".format(uom)), "fieldname": "out_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Balance Qty(per {})".format(uom)), "fieldname": "qty_after_transaction", "fieldtype": "Float", "width": 100},
	]

	return columns


def get_stock_ledger_entries(items):
	item_conditions_sql = ''
	if items:
		item_conditions_sql = 'and sle.item_code in ({})'\
			.format(', '.join(frappe.db.escape(i) for i in items))

	sl_entries = frappe.db.sql("""
		SELECT
			name AS ID,
			concat_ws(" ", posting_date, posting_time) AS date,
			creation,
			item_code,
			actual_qty,
			stock_uom,
			qty_after_transaction,
			voucher_type
		FROM
			`tabStock Ledger Entry` sle
		WHERE
			is_cancelled = 0 {item_conditions_sql}
		ORDER BY
			creation asc
		""".format(item_conditions_sql=item_conditions_sql), as_dict=1)

	return sl_entries


def get_items(filters):
	conditions = []
	if filters.get("item_code"):
		conditions.append("item.name=%(item_code)s")

	items = []
	if conditions:
		items = frappe.db.sql_list("""select name from `tabItem` item where {}"""
			.format(" and ".join(conditions)), filters)
	return items


def get_item_details(items, sl_entries):
	item_details = {}
	if not items:
		items = list(set(d.item_code for d in sl_entries))

	if not items:
		return item_details

	res = frappe.db.sql("""
		select
			item.name, item.item_name, item.stock_uom
		from
			`tabItem` item
			
		where
			item.name in ({item_codes})
	""".format(item_codes=','.join(['%s'] *len(items))), items, as_dict=1)

	for item in res:
		item_details.setdefault(item.name, item)

	return item_details

// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.accounts.dimensions");

frappe.ui.form.on('IaT Value Adjustment', {
	setup: function (frm) {
		frm.add_fetch('company', 'cost_center', 'cost_center');
		frm.set_query('cost_center', function () {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0
				}
			}
		});
		frm.set_query('iat', function () {
			return {
				filters: {
					calculate_depreciation: 1,
					docstatus: 1
				}
			};
		});
	},

	onload: function (frm) {
		if (frm.is_new() && frm.doc.iat) {
			frm.trigger("set_current_iat_value");
		}

		erpnext.accounts.dimensions.setup_dimension_filters(frm, frm.doctype);
	},

	company: function (frm) {
		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	iat: function (frm) {
		frm.trigger("set_current_iat_value");
	},

	finance_book: function (frm) {
		frm.trigger("set_current_iat_value");
	},

	set_current_iat_value: function (frm) {
		if (frm.doc.iat) {
			frm.call({
				method: "erpnext.instrument.doctype.iat_value_adjustment.iat_value_adjustment.get_current_iat_value",
				args: {
					iat: frm.doc.iat,
					finance_book: frm.doc.finance_book
				},
				callback: function (r) {
					if (r.message) {
						frm.set_value('current_iat_value', r.message);
					}
				}
			});
		}
	}
});

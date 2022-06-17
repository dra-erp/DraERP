// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.iat");
frappe.provide("erpnext.accounts.dimensions");

frappe.ui.form.on('IaT', {
	onload: function (frm) {
		frm.set_query("item_code", function () {
			return {
				"filters": {
					"is_fixed_asset": 1,
					"is_stock_item": 1
				}
			};
		});

		frm.set_query("warehouse", function () {
			return {
				"filters": {
					"company": frm.doc.company,
					"is_group": 0
				}
			};
		});

		frm.set_query("department", function () {
			return {
				"filters": {
					"company": frm.doc.company,
				}
			};
		});

		erpnext.accounts.dimensions.setup_dimension_filters(frm, frm.doctype);
	},

	company: function (frm) {
		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	setup: function (frm) {
		frm.make_methods = {
			'Iat Movement': () => {
				frappe.call({
					method: "erpnext.instrument.doctype.iat.iat.make_iat_movement",
					freeze: true,
					args: {
						"iat": [{ name: cur_frm.doc.name }]
					},
					callback: function (r) {
						if (r.message) {
							var doc = frappe.model.sync(r.message)[0];
							frappe.set_route("Form", doc.doctype, doc.name);
						}
					}
				});
			},
		}

		frm.set_query("purchase_receipt", (doc) => {
			return {
				query: "erpnext.controllers.queries.get_purchase_receipts",
				filters: { item_code: doc.item_code }
			}
		});
		frm.set_query("purchase_invoice", (doc) => {
			return {
				query: "erpnext.controllers.queries.get_purchase_invoices",
				filters: { item_code: doc.item_code }
			}
		});
	},

	refresh: function (frm) {
		frappe.ui.form.trigger("IaT", "is_existing_iat");
		frm.toggle_display("next_depreciation_date", frm.doc.docstatus < 1);
		frm.events.make_schedules_editable(frm);

		if (frm.doc.docstatus == 1) {
			if (in_list(["Submitted", "Partially Depreciated", "Fully Depreciated"], frm.doc.status)) {
				frm.add_custom_button(__("Transfer IaT"), function () {
					erpnext.iat.transfer_iat(frm);
				}, __("Manage"));

				frm.add_custom_button(__("Scrap IaT"), function () {
					erpnext.iat.scrap_iat(frm);
				}, __("Manage"));

				frm.add_custom_button(__("Sell IaT"), function () {
					frm.trigger("make_sales_invoice");
				}, __("Manage"));

			} else if (frm.doc.status == 'Scrapped') {
				frm.add_custom_button(__("Restore IaT"), function () {
					erpnext.iat.restore_iat(frm);
				}, __("Manage"));
			}

			if (frm.doc.maintenance_required && !frm.doc.maintenance_schedule) {
				frm.add_custom_button(__("Maintain IaT"), function () {
					frm.trigger("create_iat_maintenance");
				}, __("Manage"));
			}

			frm.add_custom_button(__("Repair IaT"), function () {
				frm.trigger("create_iat_repair");
			}, __("Manage"));

			frm.add_custom_button(__("Split IaT"), function () {
				frm.trigger("split_iat");
			}, __("Manage"));

			if (frm.doc.status != 'Fully Depreciated') {
				frm.add_custom_button(__("Adjust Iat Value"), function () {
					frm.trigger("create_iat_value_adjustment");
				}, __("Manage"));
			}

			if (!frm.doc.calculate_depreciation) {
				frm.add_custom_button(__("Create Depreciation Entry"), function () {
					frm.trigger("make_journal_entry");
				}, __("Manage"));
			}

			if (frm.doc.purchase_receipt || !frm.doc.is_existing_iat) {
				frm.add_custom_button(__("View General Ledger"), function () {
					frappe.route_options = {
						"voucher_no": frm.doc.name,
						"from_date": frm.doc.available_for_use_date,
						"to_date": frm.doc.available_for_use_date,
						"company": frm.doc.company
					};
					frappe.set_route("query-report", "General Ledger");
				}, __("Manage"));
			}

			frm.trigger("setup_chart");
		}

		frm.trigger("toggle_reference_doc");

		if (frm.doc.docstatus == 0) {
			frm.toggle_reqd("finance_books", frm.doc.calculate_depreciation);
		}
	},

	toggle_reference_doc: function (frm) {
		if (frm.doc.purchase_receipt && frm.doc.purchase_invoice && frm.doc.docstatus === 1) {
			frm.set_df_property('purchase_invoice', 'read_only', 1);
			frm.set_df_property('purchase_receipt', 'read_only', 1);
		}
		else if (frm.doc.is_existing_iat) {
			frm.toggle_reqd('purchase_receipt', 0);
			frm.toggle_reqd('purchase_invoice', 0);
		}
		else if (frm.doc.purchase_receipt) {
			// if purchase receipt link is set then set PI disabled
			frm.toggle_reqd('purchase_invoice', 0);
			frm.set_df_property('purchase_invoice', 'read_only', 1);
		}
		else if (frm.doc.purchase_invoice) {
			// if purchase invoice link is set then set PR disabled
			frm.toggle_reqd('purchase_receipt', 0);
			frm.set_df_property('purchase_receipt', 'read_only', 1);
		}
		else {
			frm.toggle_reqd('purchase_receipt', 1);
			frm.set_df_property('purchase_receipt', 'read_only', 0);
			frm.toggle_reqd('purchase_invoice', 1);
			frm.set_df_property('purchase_invoice', 'read_only', 0);
		}
	},

	make_journal_entry: function (frm) {
		frappe.call({
			method: "erpnext.instrument.doctype.iat.iat.make_journal_entry",
			args: {
				iat_name: frm.doc.name
			},
			callback: function (r) {
				if (r.message) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		})
	},

	setup_chart: function (frm) {
		var x_intervals = [frm.doc.purchase_date];
		var iat_values = [frm.doc.gross_purchase_amount];
		var last_depreciation_date = frm.doc.purchase_date;

		if (frm.doc.opening_accumulated_depreciation) {
			last_depreciation_date = frappe.datetime.add_months(frm.doc.next_depreciation_date,
				-1 * frm.doc.frequency_of_depreciation);

			x_intervals.push(last_depreciation_date);
			iat_values.push(flt(frm.doc.gross_purchase_amount) -
				flt(frm.doc.opening_accumulated_depreciation));
		}

		$.each(frm.doc.schedules || [], function (i, v) {
			x_intervals.push(v.schedule_date);
			var iat_value = flt(frm.doc.gross_purchase_amount) - flt(v.accumulated_depreciation_amount);
			if (v.journal_entry) {
				last_depreciation_date = v.schedule_date;
				iat_values.push(iat_value);
			} else {
				if (in_list(["Scrapped", "Sold"], frm.doc.status)) {
					iat_values.push(null);
				} else {
					iat_values.push(iat_value)
				}
			}
		});

		if (in_list(["Scrapped", "Sold"], frm.doc.status)) {
			x_intervals.push(frm.doc.disposal_date);
			iat_values.push(0);
			last_depreciation_date = frm.doc.disposal_date;
		}

		frm.dashboard.render_graph({
			title: "IaT Value",
			data: {
				labels: x_intervals,
				datasets: [{
					color: 'red',
					values: iat_values,
					formatted: iat_values.map(d => d.toFixed(2))
				}]
			},
			type: 'line'
		});
	},


	item_code: function (frm) {
		if (frm.doc.item_code) {
			frm.trigger('set_finance_book');
		}
	},

	set_finance_book: function (frm) {
		frappe.call({
			method: "erpnext.instrument.doctype.iat.iat.get_item_details",
			args: {
				item_code: frm.doc.item_code,
				tools_category: frm.doc.tools_category
			},
			callback: function (r, rt) {
				if (r.message) {
					frm.set_value('finance_books', r.message);
				}
			}
		})
	},

	is_existing_iat: function (frm) {
		frm.trigger("toggle_reference_doc");
		// frm.toggle_reqd("next_depreciation_date", (!frm.doc.is_existing_iat && frm.doc.calculate_depreciation));
	},

	opening_accumulated_depreciation: function (frm) {
		erpnext.iat.set_accumulated_depreciation(frm);
	},

	make_schedules_editable: function (frm) {
		if (frm.doc.finance_books) {
			var is_editable = frm.doc.finance_books.filter(d => d.depreciation_method == "Manual").length > 0
				? true : false;

			frm.toggle_enable("schedules", is_editable);
			frm.fields_dict["schedules"].grid.toggle_enable("schedule_date", is_editable);
			frm.fields_dict["schedules"].grid.toggle_enable("depreciation_amount", is_editable);
		}
	},

	make_sales_invoice: function (frm) {
		frappe.call({
			args: {
				"iat": frm.doc.name,
				"item_code": frm.doc.item_code,
				"company": frm.doc.company,
				"serial_no": frm.doc.serial_no
			},
			method: "erpnext.instrument.doctype.iat.iat.make_sales_invoice",
			callback: function (r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			}
		})
	},

	create_iat_maintenance: function (frm) {
		frappe.call({
			args: {
				"iat": frm.doc.name,
				"item_code": frm.doc.item_code,
				"item_name": frm.doc.item_name,
				"tools_category": frm.doc.tools_category,
				"company": frm.doc.company
			},
			method: "erpnext.instrument.doctype.iat.iat.create_iat_maintenance",
			callback: function (r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			}
		})
	},

	create_iat_repair: function (frm) {
		frappe.call({
			args: {
				"iat": frm.doc.name,
				"iat_name": frm.doc.iat_name
			},
			method: "erpnext.instrument.doctype.iat.iat.create_iat_repair",
			callback: function (r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			}
		});
	},

	split_iat: function (frm) {
		const title = __('Split IaT');

		const fields = [
			{
				fieldname: 'split_qty',
				fieldtype: 'Int',
				label: __('Split Qty'),
				reqd: 1
			}
		];

		let dialog = new frappe.ui.Dialog({
			title: title,
			fields: fields
		});

		dialog.set_primary_action(__('Split'), function () {
			const dialog_data = dialog.get_values();
			frappe.call({
				args: {
					"iat_name": frm.doc.name,
					"split_qty": cint(dialog_data.split_qty)
				},
				method: "erpnext.instrument.doctype.iat.iat.split_iat",
				callback: function (r) {
					let doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			});

			dialog.hide();
		});

		dialog.show();
	},

	create_iat_value_adjustment: function (frm) {
		frappe.call({
			args: {
				"iat": frm.doc.name,
				"tools_category": frm.doc.tools_category,
				"company": frm.doc.company
			},
			method: "erpnext.instrument.doctype.iat.iat.create_iat_value_adjustment",
			freeze: 1,
			callback: function (r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			}
		})
	},

	calculate_depreciation: function (frm) {
		frm.toggle_reqd("finance_books", frm.doc.calculate_depreciation);
	},

	gross_purchase_amount: function (frm) {
		frm.doc.finance_books.forEach(d => {
			frm.events.set_depreciation_rate(frm, d);
		})
	},

	purchase_receipt: (frm) => {
		frm.trigger('toggle_reference_doc');
		if (frm.doc.purchase_receipt) {
			if (frm.doc.item_code) {
				frappe.db.get_doc('Purchase Receipt', frm.doc.purchase_receipt).then(pr_doc => {
					frm.events.set_values_from_purchase_doc(frm, 'Purchase Receipt', pr_doc)
				});
			} else {
				frm.set_value('purchase_receipt', '');
				frappe.msgprint({
					title: __('Not Allowed'),
					message: __("Please select Item Code first")
				});
			}
		}
	},

	purchase_invoice: (frm) => {
		frm.trigger('toggle_reference_doc');
		if (frm.doc.purchase_invoice) {
			if (frm.doc.item_code) {
				frappe.db.get_doc('Purchase Invoice', frm.doc.purchase_invoice).then(pi_doc => {
					frm.events.set_values_from_purchase_doc(frm, 'Purchase Invoice', pi_doc)
				});
			} else {
				frm.set_value('purchase_invoice', '');
				frappe.msgprint({
					title: __('Not Allowed'),
					message: __("Please select Item Code first")
				});
			}
		}
	},

	set_values_from_purchase_doc: function (frm, doctype, purchase_doc) {
		frm.set_value('company', purchase_doc.company);
		frm.set_value('purchase_date', purchase_doc.posting_date);
		const item = purchase_doc.items.find(item => item.item_code === frm.doc.item_code);
		if (!item) {
			doctype_field = frappe.scrub(doctype)
			frm.set_value(doctype_field, '');
			frappe.msgprint({
				title: __('Invalid {0}', [__(doctype)]),
				message: __('The selected {0} does not contain the selected iat Item.', [__(doctype)]),
				indicator: 'red'
			});
		}
		frm.set_value('gross_purchase_amount', item.base_net_rate + item.item_tax_amount);
		frm.set_value('purchase_receipt_amount', item.base_net_rate + item.item_tax_amount);
		item.iat_location && frm.set_value('location', item.iat_location);
		frm.set_value('cost_center', item.cost_center || purchase_doc.cost_center);
	},

	set_depreciation_rate: function (frm, row) {
		if (row.total_number_of_depreciations && row.frequency_of_depreciation
			&& row.expected_value_after_useful_life) {
			frappe.call({
				method: "get_depreciation_rate",
				doc: frm.doc,
				args: row,
				callback: function (r) {
					if (r.message) {
						frappe.flags.dont_change_rate = true;
						frappe.model.set_value(row.doctype, row.name,
							"rate_of_depreciation", flt(r.message, precision("rate_of_depreciation", row)));
					}
				}
			});
		}
	}
});

frappe.ui.form.on('IaT Finance Book', {
	depreciation_method: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frm.events.set_depreciation_rate(frm, row);
		frm.events.make_schedules_editable(frm);
	},

	expected_value_after_useful_life: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frm.events.set_depreciation_rate(frm, row);
	},

	frequency_of_depreciation: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frm.events.set_depreciation_rate(frm, row);
	},

	total_number_of_depreciations: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frm.events.set_depreciation_rate(frm, row);
	},

	rate_of_depreciation: function (frm, cdt, cdn) {
		if (!frappe.flags.dont_change_rate) {
			frappe.model.set_value(cdt, cdn, "expected_value_after_useful_life", 0);
		}

		frappe.flags.dont_change_rate = false;
	},

	depreciation_start_date: function (frm, cdt, cdn) {
		const book = locals[cdt][cdn];
		if (frm.doc.available_for_use_date && book.depreciation_start_date == frm.doc.available_for_use_date) {
			frappe.msgprint(__("Depreciation Posting Date should not be equal to Available for Use Date."));
			book.depreciation_start_date = "";
			frm.refresh_field("finance_books");
		}
	}
});

frappe.ui.form.on('Depreciation Schedule', {
	make_depreciation_entry: function (frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (!row.journal_entry) {
			frappe.call({
				method: "erpnext.instrument.doctype.iat.depreciation.make_depreciation_entry",
				args: {
					"iat_name": frm.doc.name,
					"date": row.schedule_date
				},
				callback: function (r) {
					frappe.model.sync(r.message);
					frm.refresh();
				}
			})
		}
	},

	depreciation_amount: function (frm, cdt, cdn) {
		erpnext.iat.set_accumulated_depreciation(frm);
	}

})

erpnext.iat.set_accumulated_depreciation = function (frm) {
	if (frm.doc.depreciation_method != "Manual") return;

	var accumulated_depreciation = flt(frm.doc.opening_accumulated_depreciation);
	$.each(frm.doc.schedules || [], function (i, row) {
		accumulated_depreciation += flt(row.depreciation_amount);
		frappe.model.set_value(row.doctype, row.name,
			"accumulated_depreciation_amount", accumulated_depreciation);
	})
};

erpnext.iat.scrap_iat = function (frm) {
	frappe.confirm(__("Do you really want to scrap this iat?"), function () {
		frappe.call({
			args: {
				"iat_name": frm.doc.name
			},
			method: "erpnext.instrument.doctype.iat.depreciation.scrap_iat",
			callback: function (r) {
				cur_frm.reload_doc();
			}
		})
	})
};

erpnext.iat.restore_iat = function (frm) {
	frappe.confirm(__("Do you really want to restore this scrapped iat?"), function () {
		frappe.call({
			args: {
				"iat_name": frm.doc.name
			},
			method: "erpnext.instrument.doctype.iat.depreciation.restore_iat",
			callback: function (r) {
				cur_frm.reload_doc();
			}
		})
	})
};

erpnext.iat.transfer_iat = function () {
	frappe.call({
		method: "erpnext.instrument.doctype.iat.iat.make_iat_movement",
		freeze: true,
		args: {
			"iat": [{ name: cur_frm.doc.name }],
			"purpose": "Transfer"
		},
		callback: function (r) {
			if (r.message) {
				var doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		}
	});
};

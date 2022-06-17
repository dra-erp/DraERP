// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('IaT Movement', {
	setup: (frm) => {
		frm.set_query("to_employee", "instrument", (doc) => {
			return {
				filters: {
					company: doc.company
				}
			};
		})
		frm.set_query("from_employee", "instrument", (doc) => {
			return {
				filters: {
					company: doc.company
				}
			};
		})
		frm.set_query("reference_name", (doc) => {
			return {
				filters: {
					company: doc.company,
					docstatus: 1
				}
			};
		})
		frm.set_query("reference_doctype", () => {
			return {
				filters: {
					name: ["in", ["Purchase Receipt", "Purchase Invoice"]]
				}
			};
		}),
		frm.set_query("iat", "instrument", () => {
			return {
				filters: {
					status: ["not in", ["Draft"]]
				}
			}
		})
	},

	onload: (frm) => {
		frm.trigger('set_required_fields');
	},

	purpose: (frm) => {
		frm.trigger('set_required_fields');
	},

	set_required_fields: (frm, cdt, cdn) => {
		let fieldnames_to_be_altered;
		if (frm.doc.purpose === 'Transfer') {
			fieldnames_to_be_altered = {
				target_location: { read_only: 0, reqd: 1 },
				source_location: { read_only: 1, reqd: 1 },
				from_employee: { read_only: 1, reqd: 0 },
				to_employee: { read_only: 1, reqd: 0 }
			};
		}
		else if (frm.doc.purpose === 'Receipt') {
			fieldnames_to_be_altered = {
				target_location: { read_only: 0, reqd: 1 },
				source_location: { read_only: 1, reqd: 0 },
				from_employee: { read_only: 0, reqd: 1 },
				to_employee: { read_only: 1, reqd: 0 }
			};
		}
		else if (frm.doc.purpose === 'Issue') {
			fieldnames_to_be_altered = {
				target_location: { read_only: 1, reqd: 0 },
				source_location: { read_only: 1, reqd: 1 },
				from_employee: { read_only: 1, reqd: 0 },
				to_employee: { read_only: 0, reqd: 1 }
			};
		}
		Object.keys(fieldnames_to_be_altered).forEach(fieldname => {
			let property_to_be_altered = fieldnames_to_be_altered[fieldname];
			Object.keys(property_to_be_altered).forEach(property => {
				let value = property_to_be_altered[property];
				frm.set_df_property(fieldname, property, value, cdn, 'instrument');
			});
		});
		frm.refresh_field('instrument');
	}
});

frappe.ui.form.on('IaT Movement Item', {
	iat: function(frm, cdt, cdn) {
		// on manual entry of an iat auto sets their source location / employee
		const iat_name = locals[cdt][cdn].iat;
		if (iat_name){
			frappe.db.get_doc('IaT', iat_name).then((iat_doc) => {
				if(iat_doc.location) frappe.model.set_value(cdt, cdn, 'source_location', iat_doc.location);
				if(iat_doc.custodian) frappe.model.set_value(cdt, cdn, 'from_employee', iat_doc.custodian);
			}).catch((err) => {
				console.log(err); // eslint-disable-line
			});
		}
	}
});

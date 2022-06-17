// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('IaT Maintenance Log', {
	asset_maintenance: (frm) => {
		frm.set_query('task', function(doc) {
			return {
				query: "erpnext.instrument.doctype.iat_maintenance_log.iat_maintenance_log.get_maintenance_tasks",
				filters: {
					'iat_maintenance': doc.iat_maintenance
				}
			};
		});
	}
});

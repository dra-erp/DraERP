# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from erpnext.instrument.doctype.iat_maintenance.iat_maintenance import calculate_next_due_date

class IaTMaintenanceLog(Document):
    def validate(self):
        if getdate(self.due_date) < getdate(nowdate()) and self.maintenance_status not in ["Completed", "Cancelled"]:
            self.maintenance_status = "Overdue"

        if self.maintenance_status == "Completed" and not self.completion_date:
            frappe.throw(_("Please select Completion Date for Completed IaT Maintenance Log"))

        if self.maintenance_status != "Completed" and self.completion_date:
            frappe.throw(_("Please select Maintenance Status as Completed or remove Completion Date"))

    def on_submit(self):
        if self.maintenance_status not in ['Completed', 'Cancelled']:
            frappe.throw(_("Maintenance Status has to be Cancelled or Completed to Submit"))
        self.update_maintenance_task()

    def update_maintenance_task(self):
        iat_maintenance_doc = frappe.get_doc('IaT Maintenance Task', self.task)
        if self.maintenance_status == "Completed":
            if iat_maintenance_doc.last_completion_date != self.completion_date:
                next_due_date = calculate_next_due_date(periodicity = self.periodicity, last_completion_date = self.completion_date)
                iat_maintenance_doc.last_completion_date = self.completion_date
                iat_maintenance_doc.next_due_date = next_due_date
                iat_maintenance_doc.maintenance_status = "Planned"
                iat_maintenance_doc.save()
        if self.maintenance_status == "Cancelled":
            iat_maintenance_doc.maintenance_status = "Cancelled"
            iat_maintenance_doc.save()
        iat_maintenance_doc = frappe.get_doc('IaT Maintenance', self.iat_maintenance)
        iat_maintenance_doc.save()

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_maintenance_tasks(doctype, txt, searchfield, start, page_len, filters):
    iat_maintenance_tasks = frappe.db.get_values('IaT Maintenance Task', {'parent':filters.get("iat_maintenance")}, 'maintenance_task')
    return iat_maintenance_tasks

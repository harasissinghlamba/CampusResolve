from django import forms

from apps.accounts.models import Department
from apps.complaints.models import Complaint, Status
from apps.complaints.widgets import bootstrapify


class ForwardToDepartmentForm(forms.Form):
    department = forms.ChoiceField(choices=Department.choices, label="Forward to HOD of")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class StatusChangeForm(forms.Form):
    new_status = forms.ChoiceField(choices=Status.choices)
    remark = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class DirectorRemarkForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ["director_public_remark", "director_internal_note"]
        widgets = {
            "director_public_remark": forms.Textarea(attrs={"rows": 3}),
            "director_internal_note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "director_public_remark": "Visible to the student.",
            "director_internal_note": "Internal only - never shown to students.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)

from django import forms

from apps.complaints.models import Status
from apps.complaints.widgets import bootstrapify


class HodStatusChangeForm(forms.Form):
    new_status = forms.ChoiceField(choices=Status.choices)
    remark = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class HodRemarkForm(forms.Form):
    hod_remark = forms.CharField(
        label="Department remark (visible to the student)",
        widget=forms.Textarea(attrs={"rows": 3}), required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)

from django import forms

from .models import Attachment, Complaint, ComplaintCategory
from .widgets import bootstrapify


class AttachmentUploadForm(forms.Form):
    file = forms.FileField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class ComplaintForm(forms.ModelForm):
    """
    Student-facing complaint form. Deliberately excludes `student`, `status`,
    `spam_score`, `spam_classification`, `director_public_remark`, and
    `director_internal_note` - none of those are ever settable by a student.
    """

    class Meta:
        model = Complaint
        fields = [
            "category",
            "subject",
            "description",
            "department_or_location",
            "student_urgency",
            "is_confidential",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ComplaintCategory.objects.filter(is_active=True)
        self.fields["category"].empty_label = "Select a category"
        bootstrapify(self)

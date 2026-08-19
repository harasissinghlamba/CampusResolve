from django import forms


def bootstrapify(form: forms.BaseForm) -> None:
    """Add Bootstrap 5 classes to every widget on a form. Called from each
    form's __init__ so templates can render {{ field }} directly."""
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = (existing + " form-check-input").strip()
        elif isinstance(widget, forms.Select):
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = (existing + " form-select").strip()
        else:
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = (existing + " form-control").strip()

from django.contrib import messages
from django.shortcuts import redirect, render

from apps.accounts.permissions import role_required
from apps.audit.models import audit
from core.rules import RuleSetError, load_default_ruleset, parse_ruleset
from .models import RuleSetVersion
from .rulesets import active_ruleset


@role_required("is_tech_admin")
def config_home(request):
    rs, version = active_ruleset()
    rv = RuleSetVersion.objects.first()
    text = rv.yaml_text if rv else open(__import__("core.rules", fromlist=["x"]).DEFAULT_RULESET, encoding="utf-8").read()
    if request.method == "POST":
        new_text = request.POST.get("yaml_text", "")
        try:
            parsed = parse_ruleset(new_text)
        except RuleSetError as exc:
            messages.error(request, f"Configuración inválida (no se guardó): {str(exc)[:300]}")
            return render(request, "config.html", {"yaml_text": new_text, "ruleset": rs, "version": version,
                                                   "versions": RuleSetVersion.objects.all()[:20]}, status=400)
        rv = RuleSetVersion.objects.create(version=parsed.version, yaml_text=new_text, created_by=request.user)
        audit(request.user, "config.update", f"ruleset#{rv.pk}", parsed.version)
        messages.success(request, f"Nueva versión de configuración guardada (#{rv.pk}).")
        return redirect("config_home")
    return render(request, "config.html", {"yaml_text": text, "ruleset": rs, "version": version,
                                           "versions": RuleSetVersion.objects.all()[:20]})

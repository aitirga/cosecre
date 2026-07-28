"""Catalan copy that reaches a person.

AIM's users are Catalan-speaking teachers and students, so anything they read
is Catalan: the tutor's system prompt and the error details that surface in the
UI. The hub's own English chrome is untouched — half-translating one surface is
worse than a clean seam.

Collected here rather than inlined so the whole translated surface is one file
to grep, and so a second language is a second module rather than an archaeology
exercise.
"""

from __future__ import annotations

# ── Roster ──────────────────────────────────────────────────────────────────
NOT_A_MEMBER = "No tens accés a AIM. Demana-ho al teu professor."
TEACHER_ONLY = "Només el professorat pot fer aquesta acció."
STUDENT_ONLY = "Només l'alumnat pot fer aquesta acció."
LAST_TEACHER = "No pots treure l'últim professor d'AIM."
MEMBER_NOT_FOUND = "Aquesta persona no és membre d'AIM."
USER_NOT_FOUND = "Aquest usuari no existeix."
UNKNOWN_ROLE = "El rol ha de ser 'teacher' o 'student'."

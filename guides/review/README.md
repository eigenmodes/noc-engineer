# לבדיקה: מה נוסף ב-24–25 בנובמבר

כל מה שכאן עוד לא עבר את הבדיקה שלך. אחרי שבדקת ואישרת קובץ, אפשר להעביר אותו ל-`guides/` (תיקייה אחת למעלה), או להשאיר אותו כאן.

## מסמכים (בתיקייה הזאת)
| קובץ | מה יש בו | מה לבדוק / להחליט |
|---|---|---|
| `PERFORMANCE.md` | מהירות עם חשיבה דלוקה: פחות סבבים, `noc.py investigate`, cron בלי חשיבה, בקשות לצוות השרת | איך מדליקים ומכבים חשיבה ב-DeepSeek V4 אצלכם (שמות השדות). האם לבנות את `noc.py investigate`. האם יש endpoint פנימי שני למודל גיבוי (סעיף 3.8) |
| `LANGFUSE.md` | פריסה של Langfuse עם Helm, אתחול אוטומטי, חיבור Hermes מ-mirror פנימי | URL פנימי, ingress או Route, registry, כתובת ה-git של `hermes-official-plugins`, האם ה-datastores רצים תחת ה-SCC ב-OpenShift |
| `EVALS.md` | בדיקת איכות על 20 תקלות מהעבר, ציון ב-Langfuse | לבחור את 20 התקלות. האם הסף (80%, 0 דליפות) מתאים |
| `ENVIRONMENT-KNOWLEDGE.md` | מה צריך לאסוף על הרשת ואיפה כל דבר נכנס | **זה ה-TBD שלך:** טבלת hops, PromQL, דפוסי תקלות, מילון מונחים |
| `RUNBOOK.md` | מתגי כיבוי, triage, סימפטומים, חזרה לגרסה קודמת | שהפקודות מתאימות לסביבה שלכם (namespace, הרשאות kubectl) |
| `SECURITY.md` | 11 איומים, מה קיים ומה חסר | שורות 3, 5 ו-10: הרשאות קריאה בלבד ב-backends, בידוד לקוחות ב-DM, NetworkPolicy |
| `GRAFANA.md` | ייבוא הדשבורד, וההתראות | שהמטריקות מופיעות ב-Prometheus שלכם בשמות האלה |
| `USER-GUIDE.md` | מדריך לצוות וללקוחות, בעברית | הניסוח, ושם הבוט בדוגמאות (`@noc-bot`) |

## קוד וקונפיג שנוספו באותם ימים (לא זזו, הנתיבים שלהם בשימוש)
| קובץ | מה | מה לבדוק |
|---|---|---|
| `config.yaml`, בלוק `approvals:` | פקודות מסוכנות דורשות אישור בצ'אט. ב-cron ובהרצות של שאלה בודדת הן נחסמות. 39 תבניות של פקודות כתיבה נחסמות תמיד | שאין ברשימה פקודה שהבוט כן צריך |
| `config.yaml`, `model:` | DeepSeek V4 במקום Kimi | model id ו-base_url אמיתיים |
| `deploy/langfuse/` | `values.yaml`, `secret.example.yaml`, `install.sh`, `bootstrap.py` | ערכי ה-TBD ב-`values.yaml` |
| `deploy/grafana/hermes-noc-dashboard.json` | דשבורד עם 23 פאנלים | לייבא ולראות שהפאנלים מתמלאים |
| `deploy/monitoring.yaml` | תיקון: ה-label הוא `hermes_platform` ולא `platform` | — |
| `deploy/Dockerfile`, `deploy/start.sh` | חבילת `langfuse` מותקנת ל-Python של Hermes, וה-plugin מותקן מ-`LANGFUSE_PLUGIN_SOURCE` | build עם `PIP_INDEX_URL` של ה-mirror |
| `deploy/e2e_check.py` | בדיקה חדשה: `langfuse.tracing` | — |
| `evals/run_evals.py`, `evals/cases.example.yaml` | מריץ את סט הבדיקות | הפורמט של התקלות |

## לא אומת על המערכת שלכם
- הדשבורד מול Prometheus אמיתי. יש התקנות שמוסיפות סיומת יחידה לשם המטריקה.
- התקנת ה-plugin של Langfuse מה-mirror.
- איך DeepSeek V4 אצלכם מגיב ל-`reasoning_effort`.
- פריסה של Langfuse ב-OpenShift.

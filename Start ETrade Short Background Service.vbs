' Standalone short_worker --service is RETIRED.
' Use the main Finance stack instead:
'   Start ETrade Background Service.vbs
'   or Start Silent Worker Only.vbs
' Manual one-shots still available: python short_worker.py --plan / --day / --force-dry-run
Option Explicit
' No-op on purpose (keeps old Startup shortcuts from relaunching a second worker).
WScript.Quit 0

' Launches Start CutDeck.cmd with no visible console window. This is what the
' UXP panel's helperStart.js targets via shell.openPath — UXP cannot pass a
' hidden-window flag to a launched process itself, but wscript.exe launching
' a .vbs shows no window of its own, and WshShell.Run's windowStyle 0 hides
' the console it starts, including the python.exe it runs.
'
' If the helper silently fails to come up, this gives no visible error —
' run "Start CutDeck.cmd" directly to see the real output.
Dim fso, shell, scriptDir, cmdPath
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
cmdPath = scriptDir & "\Start CutDeck.cmd"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = scriptDir
shell.Run """" & cmdPath & """", 0, False

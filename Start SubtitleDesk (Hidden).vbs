Set subtitleDeskShell = CreateObject("WScript.Shell")
Set subtitleDeskFS = CreateObject("Scripting.FileSystemObject")
subtitleDeskDir = subtitleDeskFS.GetParentFolderName(WScript.ScriptFullName)
subtitleDeskShell.Run Chr(34) & subtitleDeskDir & "\Start SubtitleDesk.cmd" & Chr(34), 0, False

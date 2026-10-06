Set clubFridayShell = CreateObject("WScript.Shell")
Set clubFridayFS = CreateObject("Scripting.FileSystemObject")
clubFridayDir = clubFridayFS.GetParentFolderName(WScript.ScriptFullName)
clubFridayShell.Run Chr(34) & clubFridayDir & "\Start ClubFriday.cmd" & Chr(34), 0, False

Set oWS = WScript.CreateObject("WScript.Shell")
strDesktop = oWS.SpecialFolders("Desktop")
scriptDir = oWS.CurrentDirectory

Set oLink = oWS.CreateShortcut(strDesktop & "\HD Clearance Tracker.lnk")
oLink.TargetPath = scriptDir & "\dist\HD-Tracker\HD-Tracker.exe"
oLink.WorkingDirectory = scriptDir & "\dist"
oLink.IconLocation = scriptDir & "\icon.ico"
oLink.Description = "HD Clearance Tracker"
oLink.Save

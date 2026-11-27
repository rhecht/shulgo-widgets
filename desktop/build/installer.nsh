; What the Windows uninstaller asks before it goes.
;
; Removing the program is not the same as removing what the program knows about you. Add or Remove
; Programs takes away the files it installed and leaves %APPDATA%\shulgo-desktop behind: your
; settings, your place, and the key that links this computer to your ShulGo account, which goes on
; being listed as a live device on your account until somebody unlinks it.
;
; electron-builder has `deleteAppDataOnUninstall` for this, and it does not apply here: its own
; schema says "one-click installer only", and ShulGo's is the assisted kind so that people can
; choose where it goes. Hence this macro, which does the same thing and has the manners to ask.
;
; Asked rather than assumed, and defaulting to No, because reinstalling is the ordinary reason
; somebody uninstalls, and nobody wants to link their computer again over a tick box they did not
; read. ${isUpdated} is true when the installer is replacing an existing copy rather than a person
; removing it, and nothing is asked or deleted then.

!macro customUnInstall
  ${ifNot} ${isUpdated}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
      "Also remove your ShulGo settings from this computer?$\r$\n$\r$\n\
This deletes the place you chose and the key that links this computer to your ShulGo account. \
Choose No if you are reinstalling.$\r$\n$\r$\n\
Either way, you can unlink this computer at shulgo.com/account/devices." \
      /SD IDNO IDNO keepTheirSettings
      RMDir /r "$APPDATA\shulgo-desktop"
    keepTheirSettings:
  ${endIf}
!macroend

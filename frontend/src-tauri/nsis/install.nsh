; Fix for "Phantom Checkbox" (Missing Translations)
; Defines the text for the "Create Desktop Shortcut" checkbox in Vietnamese to prevent empty label.

!include "MUI2.nsh"

; Define strings for English (Fallback)
LangString launch_checkbox_text ${LANG_ENGLISH} "Launch Hinto"
LangString desktop_shortcut_text ${LANG_ENGLISH} "Create Desktop Shortcut"

; Define strings for Vietnamese (The Fix)
LangString launch_checkbox_text ${LANG_VIETNAMESE} "Khởi chạy Hinto ngay"
LangString desktop_shortcut_text ${LANG_VIETNAMESE} "Tạo lối tắt trên màn hình (Desktop Shortcut)"

; Inject into Tauri's internal variables if possible, or override MUI defines.
; Note: Tauri v2's default template might use specific variable names.
; We try to override the standard MUI defines which Tauri likely relies on.

!define MUI_FINISHPAGE_RUN_TEXT $(launch_checkbox_text)
; There isn't a standard MUI define for "Create Desktop Shortcut", it's often a custom Tauri addition.
; However, defining the LangString might be picked up if Tauri uses the standard ID.

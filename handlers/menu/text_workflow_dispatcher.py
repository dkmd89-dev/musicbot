# handlers/menu/text_workflow_dispatcher.py
# -*- coding: utf-8 -*-

from logger import get_module_logger


class TextWorkflowDispatcher:
    """
    Verantwortlich für Abbruch-Erkennung ("/cancel") und den Dispatch von
    Freitext-Nachrichten an den zuständigen Multi-Step-Workflow-Handler
    (z.B. UserManagementHandler.process_new_user_id während "Neuen Nutzer
    hinzufügen"). Enthält bewusst NICHT `user_states` (URL-Erwartung) oder
    die Navidrome-Suchlogik — beides bleibt Eigentum von RichMenuHandler
    bzw. NavidromeMenuHandler, da es keine Workflow-Dispatch-Logik ist.

    `user_mgmt_handler` wird bei jedem `try_dispatch()`-Aufruf frisch vom
    Aufrufer übergeben statt einmalig injiziert zu werden: RichMenuHandler
    setzt `self.user_mgmt_handler` teils direkt (in `initialize()`), teils
    über `set_user_mgmt_handler()` — eine einmalige Registrierung würde den
    Direktzuweisungs-Pfad verpassen.
    """

    CANCEL_COMMANDS = {"/cancel", "cancel", "abbrechen"}

    # Workflow-Name -> Methodenname auf dem übergebenen user_mgmt_handler.
    WORKFLOW_METHODS = {
        "add_user_id": "process_new_user_id",
        "add_user_navidrome": "process_new_navidrome_user",
        "edit_navidrome_user": "process_edit_navidrome_user",
    }

    def __init__(self, logger=None):
        self.logger = logger or get_module_logger("TextWorkflowDispatcher")

    def is_cancel_command(self, text: str) -> bool:
        return text.lower() in self.CANCEL_COMMANDS

    async def try_dispatch(self, update, context, text: str, user_mgmt_handler) -> bool:
        """
        Prüft auf einen aktiven Workflow (`context.user_data["workflow"]`)
        und dispatcht die Nachricht an die zuständige Methode auf
        `user_mgmt_handler`. Gibt True zurück, wenn ein aktiver Workflow
        vorlag und behandelt wurde (der Aufrufer soll dann keine weitere
        Verarbeitung mehr durchführen) — sonst False.
        """
        workflow = context.user_data.get("workflow")
        if not workflow:
            return False

        self.logger.debug(f"📝 Aktiver Workflow erkannt: {workflow}")

        method_name = self.WORKFLOW_METHODS.get(workflow)
        if not method_name:
            return False

        if user_mgmt_handler and hasattr(user_mgmt_handler, method_name):
            await getattr(user_mgmt_handler, method_name)(update, context, text)
        else:
            await update.message.reply_text(
                f"❌ Handler für Workflow '{workflow}' nicht verfügbar."
            )
            context.user_data.clear()
        return True

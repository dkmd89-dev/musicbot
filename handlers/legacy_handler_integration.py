from handlers.command_integration import CommandIntegration

class LegacyHandlerIntegration(CommandIntegration):
    """Erweitert Command-Integration um bestehende Handler"""

    def register_handlers(self, application):
        # Registriere neue Menü-Handler
        super().register_handlers(application)

        # Registriere bestehende Handler
        from handlers.statistik_handler import StatistikHandler

        stats_handler = StatistikHandler(self.config, self.logger_factory)

        application.add_handler(CommandHandler("stats", stats_handler.handle_stats))
```

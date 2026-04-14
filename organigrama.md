# Organigrama de la aplicación

Este diagrama muestra la estructura principal del bot de trading y sus dependencias.

```mermaid
flowchart LR
    subgraph App[Bot de trading]
        BOT[bot.py\nPrincipal] --> CM[config_manager.py\nCarga parámetros]
        BOT --> PM[position_manager.py\nGestión de posiciones]
        BOT --> BU[binance_utils.py\nWrapper Binance]
        BOT --> TH[telegram_handler.py\nTelegram]
        BOT --> TL[trading_logic.py\nLógica de trading]
        BOT --> RT[range_trading.py\nDetección de rango]
        BOT --> RM[reporting_manager.py\nReportes CSV]
        BOT --> AI[ai_optimizer.py\nOptimización IA]
        BOT --> FU[firestore_utils.py\nPersistencia Firestore]
        CM --> FU
        PM --> FU
        RM --> TH
        RM --> FU
        TL --> BU
        RT --> BU
        AI --> BU
        TH --> Telegram[Telegram API]
        BU --> Binance[Binance API]
        FU --> Firestore[Firestore]
    end
    subgraph Config[Archivos de configuración]
        CFG[config.json / bot_config.json]
        OP[open_positions.json]
    end
    CM --> CFG
    PM --> OP
    BOT --> CFG
    BOT --> OP
```

## Descripción breve

- `bot.py`: núcleo principal que inicia el ciclo, comunica con Binance, gestiona Telegram y coordina la lógica.
- `config_manager.py`: carga y guarda parámetros de configuración.
- `position_manager.py`: administra posiciones abiertas y persistencia.
- `binance_utils.py`: wrappers y utilidades para llamadas a Binance.
- `telegram_handler.py`: envía/recibe mensajes y comandos de Telegram.
- `trading_logic.py`: contiene la lógica de decisión de compra/venta.
- `range_trading.py`: detecta mercado lateral y señales de rango.
- `reporting_manager.py`: genera reportes y CSV de transacciones.
- `ai_optimizer.py`: módulo de optimización de parámetros.
- `firestore_utils.py`: conexión con Firestore para persistencia.

Servicios externos:
- Binance API
- Telegram API
- Firestore

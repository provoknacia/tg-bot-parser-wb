import requests
import json
import time
import threading
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wildberries_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные
DATA_FILE = 'wildberries_extended_data.json'
UPDATE_INTERVAL = 300  # 5 минут в секундах
last_update_time = None
data_lock = threading.Lock()
current_data = {
    "Товары": [],
    "total": 0,
    "version": 0,
    "payloadVersion": 0
}

# Состояния для ConversationHandler
SEARCH_QUERY, SEARCH_ARTICLE = range(2)

headers = {
    'accept': '*/*',
    'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'authorization': 'Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NTE0NjAyODIsInVzZXIiOiIxMjMwMDExOTAiLCJzaGFyZF9rZXkiOiIxOCIsImNsaWVudF9pZCI6IndiIiwic2Vzc2lvbl9pZCI6ImFlYmM3ZDBkMzI0NTQwYmU5ZmU1ZmRjMGFhNDVhYzEzIiwidmFsaWRhdGlvbl9rZXkiOiIzNTFmOTY5MjBkN2I0ZWNiNzkwZThiNzgzNWFlMTI4OGQ5YTZmZTQ2ODY3MWIxN2MyNjg4YmJkYzU3ZTIwYzg2IiwicGhvbmUiOiJ0R3U3czA1UmFpZ2ZieVdUTWlFWmJRPT0iLCJ1c2VyX3JlZ2lzdHJhdGlvbl9kdCI6MTY5NDAxOTgyOCwidmVyc2lvbiI6Mn0.bZ87a45w-t6_wRlQe9W37hnAPSq22QNMEddtvqYbNrGV-fKnByasQtIYZuui5Aa1r7qvKWjHGn5Doewzv4dMobZtT-SkmQBK49OORV7Yt4mK6uzutP1fs445fPibCn7voH3coDUIdFTESkVFby3Kr-XzIFTsIMrjaij1EOIYzCKvTrWtO8Jy95J-1iQeEzws26h8XXlZDyKsf2wOA1Kp15bOgPBOnxM_Ndsai-pnnd4hH-tk5g7Xgf5u_Hpbhtg16niFfRpqn06S4vuF786gclipBPc68oRMppJzgFiNgx8LSvnYr-JXLs8VLVPFk3FmnJDpzLhefNa9oRtKhG0ZCw',
    'origin': 'https://www.wildberries.ru',
    'priority': 'u=1, i',
    'referer': 'https://www.wildberries.ru/catalog/0/search.aspx',
    'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    'x-queryid': 'qid274271218174533698420250704114744',
    'x-userid': '123001190',
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение и инструкции."""
    user = update.effective_user
    logger.info(f"User {user.id} started the bot")
    await update.message.reply_html(
        rf"Привет {user.mention_html()}! Я бот для поиска товаров на Wildberries.",
        reply_markup=ReplyKeyboardMarkup([["/search", "/last_update"], ["/manual_update", "/help"]], one_time_keyboard=True)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение с помощью."""
    logger.info(f"User {update.effective_user.id} requested help")
    help_text = (
        "Доступные команды:\n"
        "/start - Начать работу с ботом\n"
        "/search - Поиск товара по артикулу\n"
        "/last_update - Проверить время последнего обновления\n"
        "/manual_update - Вручную обновить данные\n"
        "/help - Показать это сообщение\n\n"
        f"Данные автоматически обновляются каждые {UPDATE_INTERVAL//60} минут."
    )
    await update.message.reply_text(help_text)

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс поиска товара."""
    logger.info(f"User {update.effective_user.id} started search")
    await update.message.reply_text(
        "Введите поисковый запрос",
        reply_markup=ReplyKeyboardRemove()
    )
    return SEARCH_QUERY

async def search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет поисковый запрос и запрашивает артикул."""
    search_query = update.message.text
    context.user_data['search_query'] = search_query
    logger.info(f"User {update.effective_user.id} set search query: {search_query}")
    await update.message.reply_text(
        "Теперь введите артикул товара (число):",
        reply_markup=ReplyKeyboardRemove()
    )
    return SEARCH_ARTICLE

async def search_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает введенный артикул и выводит полную информацию о товаре."""
    user = update.effective_user
    try:
        product_id = int(update.message.text)
        search_query = context.user_data.get('search_query', '')
        
        logger.info(f"User {user.id} searching for product ID: {product_id} with query: '{search_query}'")
        
        # Выполняем поиск с указанным запросом
        fetch_data(search_query)
        
        product = find_product_by_id(product_id)
        
        if product:
            # Формируем сообщение со всеми полями товара
            message = f"📌 Результаты поиска по запросу '{search_query}':\n\n"
            message += f"🛍️ <b>{product.get('Название', 'Не указано')}</b>\n"
            message += f"🔹 Артикул: <b>{product.get('Айди', 'Не указан')}</b>\n"
            message += f"🏷️ Бренд: <b>{product.get('Бренд', 'Не указан')}</b>\n"
            message += f"🎨 Цвет: <b>{product.get('Цвет', 'Не указан')}</b>\n"
            message += f"⭐ Рейтинг: <b>{product.get('Рейтинг', 'Не указан')}</b>\n"
            message += f"💬 Отзывы: <b>{product.get('Отзывы', '0')}</b>\n"
            
            # Добавляем информацию о ценах
            message += f"💰 Цена: <b>{product.get('Цена', {}).get('цена', '0')} руб.</b>\n"
            if product.get('Цена', {}).get('старая цена', 0) > 0:
                message += f"💰 Старая цена: <s>{product['Цена']['старая цена']} руб.</s>\n"
            
            # Добавляем информацию о размерах
            if 'Размеры' in product and product['Размеры']:
                message += "\n📏 <b>Доступные размеры:</b>\n"
                for size in product['Размеры']:
                    message += f"  ▪ {size.get('Размер', '')} - {size.get('Цена', '')} руб. (осталось: {size.get('Количество', 0)} шт.)\n"
            else:
                message += "\nℹ️ Информация о размерах отсутствует\n"
            
            # Дополнительная информация
            message += "\n📊 <b>Дополнительная информация:</b>\n"
            message += f"  🏬 Склад: {product.get('Идентификатор склада', 'Не указан')}\n"
            message += f"  🚚 Продаж за период: {product.get('Количество продаж', '0')}\n"
            message += f"  📦 На складе: {product.get('Товара на складе', '0')} шт.\n"
            message += f"  🖼️ Фото: {product.get('Количество картинок', '0')}\n"
            
            # Добавляем рекламные данные, если они есть
            if 'Рекламные данные' in product and product['Рекламные данные']:
                ad_data = product['Рекламные данные']
                message += "\n📢 <b>Рекламные данные:</b>\n"
                message += f"  • CPM (цена за 1000 показов): {ad_data.get('cpm', 'N/A')}\n"
                message += f"  • Продвигается: {'Да' if ad_data.get('promotion', 0) == 1 else 'Нет'}\n"
                message += f"  • Позиция в промо: {ad_data.get('promoPosition', 'N/A')}\n"
                message += f"  • Общая позиция: {ad_data.get('position', 'N/A')}\n"
                message += f"  • ID рекламы: {ad_data.get('advertId', 'N/A')}\n"
                message += f"  • Тип рекламы: {ad_data.get('tp', 'N/A')}\n"
            
            # Отправляем сообщение с HTML-разметкой
            await update.message.reply_html(message)
            logger.info(f"Sent product info to user {user.id}")
        else:
            await update.message.reply_text(f"Товар с артикулом {product_id} не найден по запросу '{search_query}'.")
            logger.warning(f"Product {product_id} not found for user {user.id}")
        
    except ValueError:
        error_msg = "Ошибка: артикул должен быть числом"
        await update.message.reply_text(error_msg)
        logger.error(f"User {user.id} entered invalid article number")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущее действие."""
    logger.info(f"User {update.effective_user.id} canceled action")
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=ReplyKeyboardMarkup([["/search", "/last_update"], ["/manual_update", "/help"]], one_time_keyboard=True)
    )
    return ConversationHandler.END

async def last_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает время последнего обновления данных."""
    logger.info(f"User {update.effective_user.id} requested last update time")
    if last_update_time:
        message = f"🕒 Последнее обновление: {last_update_time.strftime('%Y-%m-%d %H:%M:%S')}"
        if 'search_query' in current_data:
            message += f"\n🔍 Последний поисковый запрос: '{current_data['search_query']}'"
    else:
        message = "Данные еще не загружались"
    await update.message.reply_text(message)

async def manual_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает ручное обновление данных."""
    logger.info(f"User {update.effective_user.id} requested manual update")
    await update.message.reply_text("Введите поисковый запрос для обновления данных:")
    context.user_data['awaiting_query'] = True
    return SEARCH_QUERY

def fetch_data(search_query=''):
    global last_update_time, current_data
    
    params = {
        'ab_testing': 'false',
        'appType': '1',
        'curr': 'rub',
        'dest': '123585553',
        'hide_dtype': '13',
        'lang': 'ru',
        'page': '1',
        'query': search_query,
        'resultset': 'catalog',
        'sort': 'popular',
        'spp': '30',
        'suppressSpellcheck': 'false',
        'uclusters': '1',
        'uiv': '0',
        'uv': 'AQQAAQIBAAIEAAMDAAoACcUxSAbBr0RgRDk2s0cvu0xACDiwxMbAfLdeu7O-okN0ulK4HbYAPCdFpSUQPHvDpLAEPX46t8juvPjIdTacwHbHuTwAwFu2P8CuxepAZUQyxhVERqXcwb2_48RHR469BUYlSj9DTMWZSFo1A0AUPhDHvDiNR6ZCNDzGOyrFrMM7Rjy_f8GdM7NFVDVPRTrAJLkUPlu76lnMRRq_h0gDSAlAxUJIxoFAbMBfvD3CTsWTwXVGtsWbPkPBqThLvETA7LR9vYdJaL4PRClIaMa9ybsxEz-FxaXDncbtuX04xkIvNUxFOUeDsR09U76vxSHAOkGVvgrEvUFLNQ01dC5kxBwzNwEIRjeIMpcxpjC1AAA',
    }

    try:
        logger.info(f"Fetching data for query: '{search_query}'")
        response = requests.get('https://search.wb.ru/exactmatch/ru/common/v13/search', params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            
            new_data = {
                "Товары": [],
                "total": data.get("total", 0),
                "version": data.get("version", 0),
                "payloadVersion": data.get("payloadVersion", 0),
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "search_query": search_query
            }
            
            if 'data' in data and 'products' in data['data']:
                for product in data['data']['products']:
                    # Логирование рекламных данных, если они есть
                    if 'log' in product:
                        logger.info(f"Advert data for product {product.get('id', 'N/A')}: {product['log']}")
                    
                    # Получаем информацию о размерах
                    sizes = []
                    if 'sizes' in product:
                        for size in product['sizes']:
                            size_info = {
                                "Размер": size.get('name', 'Не указан'),
                                "Цена": size.get('price', {}).get('product', 0) / 100 if size.get('price', {}).get('product') else 0,
                                "Количество": size.get('stocks', [{}])[0].get('qty', 0)
                            }
                            sizes.append(size_info)
                    
                    # Получаем информацию о цвете
                    color = "Не указан"
                    if 'colors' in product and product['colors']:
                        color = product['colors'][0].get('name', 'Не указан')
                    
                    product_info = {
                        "Название": product.get('name', 'Не указано'),
                        "Айди": product.get('id', 0),
                        "Бренд": product.get('brand', 'Не указан'),
                        "Цвет": color,
                        "Цена": {
                            "цена": product.get('priceU', 0) / 100 if product.get('priceU') else 0,
                            "старая цена": product.get('salePriceU', 0) / 100 if product.get('salePriceU') else 0
                        },
                        "Размеры": sizes,
                        "Рейтинг": product.get('rating', 0),
                        "Отзывы": product.get('feedbacks', 0),
                        "Количество продаж": product.get('volume', 0),
                        "Товара на складе": product.get('totalQuantity', 0),
                        "Количество картинок": product.get('pics', 0),
                        "Идентификатор склада": product.get('wh', 0),
                        "Корневая категория": product.get('root', 0),
                        "Рейтинг отзывов": product.get('reviewRating', 0),
                        "Отзывы (номенклатура)": product.get('nmFeedbacks', 0),
                        "Позиция товара": product.get('rank', 0),
                        "Версия": product.get('version', 0),
                        "Рекламные данные": product.get('log', None)  # Добавляем рекламные данные в информацию о товаре
                    }
                    new_data["Товары"].append(product_info)
            
            with data_lock:
                current_data = new_data
            
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=4)
            
            last_update_time = datetime.now()
            logger.info(f"Data updated at {last_update_time.strftime('%H:%M:%S')}")
            logger.info(f"Search query: '{search_query}'")
            logger.info(f"Received {len(new_data['Товары'])} products from {new_data['total']}")
        else:
            logger.error(f"Request error: {response.status_code}")
            logger.error(f"Server response: {response.text[:200]}...")
    except Exception as e:
        logger.error(f"Error while fetching data: {str(e)}", exc_info=True)

def auto_update():
    while True:
        try:
            # Автообновление с последним использованным запросом или пустым запросом
            search_query = current_data.get('search_query', '')
            logger.info(f"Auto-updating data with query: '{search_query}'")
            fetch_data(search_query)
            time.sleep(UPDATE_INTERVAL)
        except Exception as e:
            logger.error(f"Error in auto_update: {str(e)}", exc_info=True)
            time.sleep(60)  # Подождать минуту перед повторной попыткой

def find_product_by_id(product_id):
    with data_lock:
        for product in current_data["Товары"]:
            if product["Айди"] == product_id:
                return product
    return None

def main():
    """Запуск бота."""
    logger.info("Starting bot...")
    
    try:
        # Запускаем автообновление в фоновом режиме
        update_thread = threading.Thread(target=auto_update, daemon=True)
        update_thread.start()
        
        # Первоначальная загрузка данных с пустым запросом
        fetch_data()
        
        # Создаем Application и передаем токен бота
        application = Application.builder().token("ВАШ ТОКЕН").build()
        
        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("last_update", last_update))
        application.add_handler(CommandHandler("manual_update", manual_update))
        
        # Добавляем ConversationHandler для поиска товара
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("search", search_start)],
            states={
                SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query)],
                SEARCH_ARTICLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_product)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(conv_handler)
        
        # Запускаем бота
        logger.info("Bot is running...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Bot crashed: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()

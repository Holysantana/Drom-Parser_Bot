import sys
import time
import requests
from bs4 import BeautifulSoup
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

# ====================================================================
# КОНФИГУРАЦИЯ И ПЕРЕМЕННЫЕ
# ====================================================================

TOKEN = "vk1.a.itJxLjYnB-XYdQJOp0xwbitA-HVsanMoi9bnvGjL4x-w1TFJ-MzrfwJuqNrDYlVFIDNDPR7XQD8PyWW5xqPewfDALesPvnd-HtxAKcEi0toCtMXvcTATgGSOrn8HXGbgB9EZ75QjqyII6TvXOZtRphbt4pD7RJr7MN5auwX7-XlGJvxnzdNhal1JP3_Dr5v1oKhXtgylWDfaEmgxC3M36w"
GROUP_ID = 239799603

CITY_MAP = {
    "владивосток": "vladivostok",
    "москва": "moskva",
    "новосибирск": "novosibirsk",
    "санкт-петербург": "spb",
    "спб": "spb",
    "краснодар": "krasnodar",
    "екатеринбург": "ekaterinburg",
    "нижний новгород": "nizhniy-novgorod",
    "казань": "kazan",
    "челябинск": "chelyabinsk",
    "ростов-на-дону": "rostov-na-donu",
    "все города": "all"
}

user_states = {}

# ====================================================================
# ВАЛИДАЦИЯ ВВОДА
# ====================================================================

def validate_prices(text):
    if text == "0":
        return True, None, None
        
    if "-" not in text:
        return False, None, None
        
    parts = text.split("-")
    if len(parts) != 2:
        return False, None, None
        
    min_str = parts[0].strip()
    max_str = parts[1].strip()
    
    if not min_str.isdigit() or not max_str.isdigit():
        return False, None, None
        
    if int(min_str) > int(max_str):
        return False, None, None
        
    return True, min_str, max_str


def validate_year(text):
    if text == "0":
        return True
        
    if text.isdigit():
        year_num = int(text)
        return 1900 <= year_num <= 2027
        
    if "-" in text:
        parts = text.split("-")
        if len(parts) == 2:
            y1 = parts[0].strip()
            y2 = parts[1].strip()
            if y1.isdigit() and y2.isdigit():
                return 1900 <= int(y1) <= 2027 and 1900 <= int(y2) <= 2027
                
    return False

# ====================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ И КЛАВИАТУРА
# ====================================================================

def init_user_session(user_id):
    user_states[user_id] = {
        "state": "CHOOSING_CITY",
        "city": "all",
        "price_min": None,
        "price_max": None,
        "part_name": "",
        "car_model": "",
        "results": [],
        "current_index": 0
    }


def get_city_keyboard():
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button("Владивосток", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("Москва", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("Новосибирск", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("Краснодар", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("Спб", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("Все города", color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()


def get_pagination_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("Показать еще 10", color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("Новый поиск", color=VkKeyboardColor.NEGATIVE)
    return keyboard.get_keyboard()


def send_msg(vk, peer_id, text, keyboard=None):
    payload = {
        "peer_id": peer_id,
        "message": text,
        "random_id": vk_api.utils.get_random_id()
    }
    if keyboard:
        payload["keyboard"] = keyboard
    vk.messages.send(**payload)

# ====================================================================
# БЛОК ПАРСЕРА DROM.RU
# ====================================================================

def parse_drom_parts(city_slug, query, price_min, price_max):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Referer": "https://baza.drom.ru/"
    }
    
    if city_slug and city_slug != "all":
        url = f"https://baza.drom.ru/{city_slug}/sell_spare_parts/"
    else:
        url = "https://baza.drom.ru/sell_spare_parts/"
        
    params = {"query": query}
    if price_min:
        params["price_min"] = price_min
    if price_max:
        params["price_max"] = price_max

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        print(f"[Парсер] Лог запроса: {response.url}")
        print(f"[Парсер] Код ответа сайта: {response.status_code}")
        
        if response.status_code != 200:
            return []
            
        soup = BeautifulSoup(response.text, "html.parser")
        links = []
        
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if ".html" in href and ("sell_spare_parts" in href or "bulletin" in href):
                if any(x in href for x in ["/views", "/bookmark", "bulletin_id"]):
                    continue
                full_url = href if href.startswith("http") else f"https://baza.drom.ru{href}"
                if full_url not in links:
                    links.append(full_url)
                    
        print(f"[Парсер] Найдено ссылок: {len(links)}")
        return links
    except Exception as e:
        print(f"[Ошибка парсинга]: {e}")
        return []

# ====================================================================
# БЛОК ОТДЕЛЬНЫХ ФУНКЦИЙ ОБРАБОТКИ ШАГОВ 
# ====================================================================

def handle_city_step(vk, user_id, text):
    cleaned_city = text.lower()
    if cleaned_city in CITY_MAP:
        user_states[user_id]["city"] = CITY_MAP[cleaned_city]
        user_states[user_id]["state"] = "AWAITING_PRICE"
        msg = "Укажите ценовой диапазон в формате Min-Max (пример: 1000-2000).\nЕсли цена не важна, напишите: 0"
        send_msg(vk, user_id, msg)
    else:
        user_states[user_id]["city"] = "all"
        user_states[user_id]["state"] = "AWAITING_PRICE"
        msg = f"Города '{text}' нет в списке быстрого доступа. Поиск будет производиться по всей России.\n\nУкажите диапазон цен (например: 1000-2000) или \nЕсли цена не важна, напишите: 0"
        send_msg(vk, user_id, msg)


def handle_price_step(vk, user_id, text):
    is_valid, p_min, p_max = validate_prices(text)
    if not is_valid:
        msg = "Неверный формат цен! Отправьте два числа через дефис (например: 1000-2000) или \nЕсли цена не важна, напишите: 0"
        send_msg(vk, user_id, msg)
        return
        
    user_states[user_id]["price_min"] = p_min
    user_states[user_id]["price_max"] = p_max
    user_states[user_id]["state"] = "AWAITING_NAME"
    send_msg(vk, user_id, "Введите название необходимой запчасти (например: Фара)")


def handle_name_step(vk, user_id, text):
    user_states[user_id]["part_name"] = text
    user_states[user_id]["state"] = "AWAITING_CAR"
    send_msg(vk, user_id, "Введите марку и модель автомобиля (например: Por).\nЕсли автомобиль не важен, отправьте: 0")


def handle_car_step(vk, user_id, text):
    user_states[user_id]["car_model"] = text
    user_states[user_id]["state"] = "AWAITING_YEAR"
    send_msg(vk, user_id, "Введите год выпуска машины или диапазон (например: 2002 или 1996-2001).\nЕсли год не имеет значения, отправьте: 0")


def handle_year_step(vk, user_id, text):
    if not validate_year(text):
        send_msg(vk, user_id, "Некорректный формат года! Введите четырехзначный год, диапазон через дефис или 0:")
        return
        
    send_msg(vk, user_id, "Запускаю сбор информации с сайта Дром, ожидайте...")
    
    state_data = user_states[user_id]
    query_elements = [state_data["part_name"]]
    
    if state_data["car_model"] != "0":
        query_elements.append(state_data["car_model"])
    if text != "0":
        query_elements.append(text)
        
    final_query = " ".join(query_elements)
    
    links = parse_drom_parts(
        state_data["city"], 
        final_query, 
        state_data["price_min"], 
        state_data["price_max"]
    )
    
    if not links:
        send_msg(vk, user_id, "По вашему запросу ничего не найдено. Начнем новый поиск?", get_city_keyboard())
        user_states[user_id]["state"] = "CHOOSING_CITY"
    else:
        user_states[user_id]["state"] = "SHOWING_RESULTS"
        user_states[user_id]["results"] = links
        user_states[user_id]["current_index"] = 0
        show_results_page(vk, user_id)


def show_results_page(vk, user_id):
    state_data = user_states[user_id]
    links = state_data["results"]
    start = state_data["current_index"]
    end = start + 10
    current_chunk = links[start:end]
    
    if not current_chunk:
        send_msg(vk, user_id, "Больше объявлений не найдено.", get_city_keyboard())
        user_states[user_id]["state"] = "CHOOSING_CITY"
        return

    msg_text = f"Объявления ({start + 1} - {min(end, len(links))} из {len(links)}):\n\n"
    msg_text += "\n".join(current_chunk)
    
    user_states[user_id]["current_index"] = end
    
    if end < len(links):
        send_msg(vk, user_id, msg_text, get_pagination_keyboard())
    else:
        msg_text += "\n\nВывод объявлений завершен."
        send_msg(vk, user_id, msg_text, get_city_keyboard())
        user_states[user_id]["state"] = "CHOOSING_CITY"

# ====================================================================
# ГЛАВНЫЙ ЦИКЛ БОТА
# ====================================================================

def main():
    vk_session = vk_api.VkApi(token=TOKEN)
    vk = vk_session.get_api()
    
    print("[Система] Бот успешно запущен и ожидает сообщений...")

    while True:
        try:
            longpoll = VkBotLongPoll(vk_session, int(GROUP_ID))
            
            for event in longpoll.listen():
                if event.type != VkBotEventType.MESSAGE_NEW:
                    continue
                    
                msg_obj = event.obj.message
                user_id = msg_obj["from_id"]
                text = msg_obj["text"].strip()
                
                if not text:
                    continue

                if user_id not in user_states or text.lower() in ["новый поиск", "start", "привет"]:
                    init_user_session(user_id)
                    welcome = "Привет! Давай найдем автозапчасти на Дроме.\nВыберите город из меню или введите его название вручную:"
                    send_msg(vk, user_id, welcome, get_city_keyboard())
                    continue
                    
                current_state = user_states[user_id]["state"]

                if current_state == "CHOOSING_CITY":
                    handle_city_step(vk, user_id, text)
                    
                elif current_state == "AWAITING_PRICE":
                    handle_price_step(vk, user_id, text)
                    
                elif current_state == "AWAITING_NAME":
                    handle_name_step(vk, user_id, text)
                    
                elif current_state == "AWAITING_CAR":
                    handle_car_step(vk, user_id, text)
                    
                elif current_state == "AWAITING_YEAR":
                    handle_year_step(vk, user_id, text)
                    
                elif current_state == "SHOWING_RESULTS":
                    if text == "Показать еще 10":
                        show_results_page(vk, user_id)
                    else:
                        send_msg(vk, user_id, "Используйте кнопки меню для управления списком.", get_pagination_keyboard())

        except Exception as error:
            print(f"[Защита от падения] Ошибка сети VK: {error}. Восстановление через 3 секунды...")
            time.sleep(3)
            continue

if __name__ == "__main__":
    main()
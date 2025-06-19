import cloudscraper
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import random
import json
import os
from bs4 import BeautifulSoup
from urllib3.exceptions import ReadTimeoutError
from requests.exceptions import ReadTimeout
import re
import csv
from datetime import datetime

def get_cf_cookies():
    """Получаем cookies через cloudscraper с расширенными настройками"""
    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False,
                'desktop': True
            },
            delay=15,
            interpreter='native',
        )
        
        print("Получаем cookies через CloudScraper...")
        resp = scraper.get("https://www.investing.com/news/forex-news", timeout=60)
        
        if resp.status_code == 200:
            print("Успешно получили cookies!")
            return scraper.cookies.get_dict()
        else:
            print(f"Ошибка CloudScraper: HTTP {resp.status_code}")
    except Exception as e:
        print(f"Ошибка в CloudScraper: {str(e)}")
    return None

def save_cookies(cookies, filename="cookies.json"):
    """Сохранение cookies в файл"""
    with open(filename, 'w') as f:
        json.dump(cookies, f)

def load_cookies(filename="cookies.json"):
    """Загрузка cookies из файла"""
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return None

def setup_driver():
    """Настройка Safari WebDriver"""
    options = webdriver.SafariOptions()
    return webdriver.Safari(options=options)

def human_like_scroll(driver):
    """Имитация человеческой прокрутки"""
    total_height = driver.execute_script("return document.body.scrollHeight")
    current_position = 0
    while current_position < total_height:
        scroll_amount = random.randint(100, 300)
        current_position += scroll_amount
        driver.execute_script(f"window.scrollTo(0, {current_position});")
        time.sleep(random.uniform(0.1, 0.3))

def wait_for_cloudflare(driver, timeout=30):
    """Ожидание прохождения Cloudflare проверки с увеличенным таймаутом и повторными попытками"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"Попытка {attempt + 1} из {max_retries} прохождения Cloudflare...")
            # Ждем исчезновения формы проверки
            WebDriverWait(driver, timeout).until_not(
                EC.presence_of_element_located((By.ID, "challenge-form"))
            )
            # Дополнительная проверка на наличие других элементов Cloudflare
            WebDriverWait(driver, timeout).until_not(
                EC.presence_of_element_located((By.CLASS_NAME, "cf-browser-verification"))
            )
            print("Cloudflare проверка пройдена")
            # Даем странице время на полную загрузку после проверки
            time.sleep(5)
            return True
        except TimeoutException:
            print(f"Попытка {attempt + 1} не удалась, ожидаем и пробуем снова...")
            if attempt < max_retries - 1:
                time.sleep(10)  # Увеличенное время ожидания между попытками
                driver.refresh()  # Обновляем страницу перед следующей попыткой
            else:
                print("Не удалось пройти проверку Cloudflare после всех попыток")
                return False
    return False

def parse_minutes_ago(text):
    text = text.lower()
    if 'minute' in text:
        return int(re.search(r'(\d+)', text).group(1))
    if 'hour' in text:
        return int(re.search(r'(\d+)', text).group(1)) * 60
    if 'just now' in text:
        return 0
    return 99999  # если не удалось распознать

def get_article_content_cloudscraper(url, scraper):
    """Получение содержимого статьи через cloudscraper"""
    try:
        print(f"Пытаемся получить контент через cloudscraper: {url}")
        resp = scraper.get(url, timeout=60)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            article_container = soup.find('div', class_=lambda x: x and 'articlePage' in x)
            if article_container:
                paragraphs = []
                for p in article_container.find_all('p'):
                    if not p.find_parent(attrs={'data-test': 'contextual-subscription-hook'}):
                        text = p.get_text(strip=True)
                        if text:
                            paragraphs.append(text)
                content = '\n'.join(paragraphs)
                
                # Парсим связанные инструменты
                related = []
                related_section = soup.find('div', {'data-test': 'related-instruments-section'})
                if related_section:
                    for rel in related_section.find_all('div', class_='relative'):
                        a = rel.find('a', href=True)
                        ticker = rel.find('span')
                        if a and ticker:
                            related.append({
                                'url': a['href'],
                                'ticker': ticker.get_text(strip=True)
                            })
                
                # Парсим автора
                author = None
                author_block = soup.find('span', string='Author')
                if author_block:
                    author_link = author_block.find_next('a')
                    if author_link:
                        author = author_link.get_text(strip=True)
                
                # Парсим время публикации и апдейта
                published = None
                updated = None
                for span in soup.find_all('span'):
                    if span.get_text(strip=True).lower() == 'published':
                        next_span = span.find_next_sibling('span')
                        if next_span:
                            published = next_span.get_text(strip=True)
                    if span.get_text(strip=True).lower() == 'updated':
                        next_span = span.find_next_sibling('span')
                        if next_span:
                            updated = next_span.get_text(strip=True)
                
                return content, related, author, published, updated
    except Exception as e:
        print(f"Ошибка при получении контента через cloudscraper: {str(e)}")
    return None, [], None, None, None

def get_article_publish_datetime(article):
    try:
        time_elem = article.find_element(By.CSS_SELECTOR, 'time[data-test="article-publish-date"]')
        dt_str = time_elem.get_attribute('datetime')
        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.min  # если не нашли дату, ставим минимальную

def clean_text(text):
    if not text:
        return ''
    # Удаляем любые последовательности, начинающиеся с 'вЂ' и следующих 1-3 символов (буквы, знаки), в любом регистре
    text = re.sub(r'вЂ.{0,3}', '', text, flags=re.IGNORECASE)
    return (text
        .replace('’', "'")
        .replace('‘', "'")
        .replace('"', '"')
        .replace('"', '"')
        .replace('–', '-')
        .replace('—', '-')
        .replace('…', '...')
        .replace('•', '-')
        .replace('\xa0', ' ')
        .encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    )

def main():
    # Инициализируем cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'darwin',
            'mobile': False,
            'desktop': True
        },
        delay=15,
        interpreter='native',
    )
    
    base_url = "https://www.investing.com"
    page_url = "/news/forex-news"
    results = []
    page_num = 1
    visited_pages = set()
    
    while page_url and page_url not in visited_pages:
        visited_pages.add(page_url)
        print(f"\nСобираем статьи со страницы: {base_url}{page_url}")
        resp = scraper.get(f"{base_url}{page_url}", timeout=60)
        if resp.status_code != 200:
            print(f"Ошибка при получении страницы: HTTP {resp.status_code}")
            break
        soup = BeautifulSoup(resp.text, 'html.parser')
        articles = soup.find_all('article', attrs={'data-test': 'article-item'})
        if not articles:
            print("Статей не найдено на странице!")
            break
        print(f"Найдено статей на странице: {len(articles)}")
        
        # Обрабатываем только последние 35 статей на странице
        articles_to_process = articles[-35:] if len(articles) > 35 else articles
        for article in articles_to_process:
            try:
                title_element = article.find('a', attrs={'data-test': 'article-title-link'})
                if title_element:
                    title = title_element.text.strip()
                    link = title_element['href']
                    if not link.startswith('http'):
                        link = base_url + link
                    content, related, author, published, updated = get_article_content_cloudscraper(link, scraper)
                    if content:
                        results.append({
                            'title': title,
                            'link': link,
                            'content': content,
                            'related': related,
                            'author': author,
                            'published': published,
                            'updated': updated
                        })
                        # Сохраняем в CSV
                        csv_file = 'articles_forex.csv'
                        write_header = not os.path.exists(csv_file)
                        csv_fields = ['title', 'link', 'content', 'related', 'author', 'published', 'updated']
                        if write_header:
                            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                                writer = csv.DictWriter(f, fieldnames=csv_fields)
                                writer.writeheader()
                        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.DictWriter(f, fieldnames=csv_fields)
                            writer.writerow({
                                'title': clean_text(title),
                                'link': link,
                                'content': clean_text(content),
                                'related': clean_text('; '.join([f'{r["ticker"]} ({r["url"]})' for r in related])),
                                'author': clean_text(author),
                                'published': clean_text(published),
                                'updated': clean_text(updated)
                            })
            except Exception:
                continue

        # Поиск ссылки на следующую страницу
        next_link = None
        # Новый способ поиска кнопки 'Next' по get_text(strip=True)
        next_a = None
        for a in soup.find_all('a', href=True):
            if a.get_text(strip=True).lower() == 'next':
                next_a = a
                break
        if next_a:
            next_link = next_a['href']
        else:
            pagination = soup.find('div', class_=lambda x: x and 'flex' in x and 'gap-2' in x)
            if pagination:
                next_num = page_num + 1
                for a in pagination.find_all('a', href=True):
                    try:
                        if a.text.strip().isdigit() and int(a.text.strip()) == next_num:
                            next_link = a['href']
                            break
                    except Exception:
                        continue

        if next_link:
            if not next_link.startswith('http'):
                page_url = next_link
                m = re.search(r'/news/forex-news/(\d+)', page_url)
                if m:
                    page_num = int(m.group(1))
                else:
                    page_num += 1
            else:
                break
        else:
            break
    # Выводим результаты
    print("\nУспешно собрано статей:", len(results))
    for idx, article in enumerate(results, 1):
        print(f"\n#{idx}: {article['title']}")
        print(f"Ссылка: {article['link']}")
        print(f"Контент: {article['content']}")
        print("Связанные инструменты:")
        for related in article['related']:
            print(f" - {related['ticker']} ({related['url']})")
        print(f"Автор: {article['author']}")
        print(f"Опубликовано: {article['published']}")
        print(f"Обновлено: {article['updated']}")
        print("-" * 80)

if __name__ == "__main__":
    main()
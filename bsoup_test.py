from bs4 import BeautifulSoup
import requests
import re


DEFAULT_BASE_URL = "https://www.myinstants.com"
DEFAULT_REGION = "us"


def normalize_base_url(base_url: str) -> str:
  cleaned = (base_url or DEFAULT_BASE_URL).strip().rstrip('/')
  if not cleaned:
    cleaned = DEFAULT_BASE_URL
  if not re.match(r'^https?://', cleaned, re.IGNORECASE):
    cleaned = f'https://{cleaned}'
  return cleaned


def normalize_region(region: str) -> str:
  cleaned = (region or DEFAULT_REGION).strip().strip('/')
  return cleaned or DEFAULT_REGION


def searchq(query: str, base_url: str = DEFAULT_BASE_URL):
  headers = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '3600',
      'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0'
  }
  query = query.replace(' ','+')
  base_url = normalize_base_url(base_url)
  u = f'{base_url}/en/search/?name={query}'
  response = requests.get(url=u, headers=headers, timeout=30)
  response.raise_for_status()
  content = response.content
  url_list = []
  soup = BeautifulSoup(content, 'html.parser')
  l = soup.find_all(class_="small-button")
  c = 0
  for k in l:
    u: str = k['onclick']
    k['title'] = re.findall(str(re.escape('Play')) +
                            "(.*)"+str(re.escape('sound')), k['title'])[0]
    o = u.split('\'')
    url_list.append(
        {'url': f'{base_url}{o[1]}', 'title': str(k['title'])})
    c+=1 
    if c > 9:
      break   
  return url_list

def getPage(page: str, region: str = DEFAULT_REGION, base_url: str = DEFAULT_BASE_URL):
  headers = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '3600',
      'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0'
  }
  base_url = normalize_base_url(base_url)
  region = normalize_region(region)

# this 'headers' is required for spoofing the scraper like it is a legit browser
  if int(page) == 1:  
    u = f'{base_url}/en/index/{region}/?page={page}'
  else:
    u = f'{base_url}/en/trending/{region}/?page={page}'
  response = requests.get(url=u, headers=headers, timeout=30)
  response.raise_for_status()
  content = response.content

  url_list = []
  soup = BeautifulSoup(content, 'html.parser')
  l = soup.find_all(class_="small-button")
  for k in l:
    u: str = k['onclick']
    k['title'] = re.findall(str(re.escape('Play'))+"(.*)"+str(re.escape('sound')),k['title'])[0]
    k['title'] = k['title'].strip()
    o = u.split('\'')
    url_list.append(
        {'url': f'{base_url}{o[1]}', 'title': str(k['title'])})
  return url_list



# print("WELCOME TO MYINSTANTS PYTHON DEMO !")
# print("LOADING...")
# url_list = getPage("1")
# print(f"TOTAL {len(url_list)} SOUNDS SCRAPED")

# t = True
# print('Enter \'list\' for listing the available sounds and \'exit\' for exiting the program \'page\' for changing the page.')
# while(t):
#   j:str = str(input('Enter your choice.'))
#   if j.isnumeric():
#     if (int(j) > len(url_list)):
#       print('Out of list range.')
#     else:
#       q:vlc.MediaPlayer = vlc.MediaPlayer(url_list[int(j)-1]['url'])
#       q.play()
#   elif j == 'page':
#     g = int(input('Enter page number.'))
#     print('Wait while we load the new page')
#     url_list = getPage(str(g))
#     print('PAGE LOADED !')
#   elif j == 'list':
#     c = 1
#     for v in url_list:
#       print(f"{c}. {v['title']} \n")
#       c = c + 1
#   elif j =='exit':
#     t=False
#   else:
#     print('Command not recognised.')


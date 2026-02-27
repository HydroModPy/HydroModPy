import requests
for url in [
    "https://hubeau.eaufrance.fr/api/v1/qualite_nappes/stations",
]:
    try:
        r = requests.get(url, params={'size':1,'format':'json'}, timeout=10)
        print(url, r.status_code)
        print(r.text[:200])
    except Exception as e:
        print(url, 'error', e)

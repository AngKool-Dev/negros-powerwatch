import requests
headers = {'Origin': 'https://negros-powerwatch.pages.dev'}
try:
    r = requests.get('https://negros-powerwatch-worker.asoniojohnpaul.workers.dev/api/v1/status', headers=headers)
    print('Status:', r.status_code)
    data = r.json()
    print('Active outages:', data.get('active_outages'))
    for outage in data.get('outages', []):
        print(f"  Outage {outage['id']}: status={outage['status']}, reports={outage['report_count']}")
except Exception as e:
    print('Error:', e)

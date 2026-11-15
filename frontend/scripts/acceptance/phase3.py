"""Optional real-browser acceptance; does not start services or reset a database.

Prerequisites: Python websocket-client, Chrome with --remote-debugging-port=9223,
Vite at http://127.0.0.1:5173, and the API using the SAME temporary SQLite file.
API environment: AGENTCONNECT_ENABLE_FAKE=true, AGENTCONNECT_DEV_INVITATIONS=true,
AGENTCONNECT_ENV=development, AGENTCONNECT_LIMITS={"cooldown_seconds":0}, GEMINI_API_KEY=.
Example: python frontend/scripts/acceptance/phase3.py --database /tmp/p3-acceptance.db
An existing migrated temporary DB is required. Only generated test tenants are used;
the expiry assertion updates only their approval fixture. No live provider is called.
"""
import argparse, sys, tempfile
from urllib.parse import urlparse
import base64, json, time, urllib.request, websocket
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database',required=True,type=Path,help='Same migrated temporary SQLite file configured on the acceptance API')
parser.add_argument('--frontend-url',default='http://127.0.0.1:5173')
parser.add_argument('--cdp-url',default='http://127.0.0.1:9223')
parser.add_argument('--worker-python',type=Path,help='Backend virtual environment Python; auto-detected from the repository when omitted')
parser.add_argument('--artifacts',type=Path,default=Path(tempfile.gettempdir())/'agentconnect-phase3-artifacts')
args=parser.parse_args()
for url in [args.frontend_url,args.cdp_url]:
    parsed=urlparse(url)
    if parsed.scheme not in {'http','https'} or parsed.hostname not in {'127.0.0.1','localhost','::1'} or parsed.username:
        parser.error('Acceptance URLs must be loopback addresses without credentials')
database=args.database.resolve()
if not database.is_file() or not database.is_relative_to(Path(tempfile.gettempdir()).resolve()):
    parser.error('--database must be an existing migrated file inside the system temporary directory')
repo=Path(__file__).resolve().parents[3]
executable=Path('Scripts/python.exe') if sys.platform=='win32' else Path('bin/python')
worker_python=args.worker_python or next((path for path in [repo/'.venv'/executable,repo/'backend'/'.venv'/executable] if path.is_file()),None)
if worker_python is None or not worker_python.is_file():parser.error('Provide --worker-python for the backend virtual environment')
artifacts=args.artifacts.resolve();artifacts.mkdir(parents=True,exist_ok=True)
base=args.frontend_url.rstrip('/')
version=json.load(urllib.request.urlopen(args.cdp_url.rstrip('/')+'/json/version'))
ws=websocket.create_connection(version['webSocketDebuggerUrl'],suppress_origin=True,timeout=1)
seq=0
requests=[]
contexts=[]
errors=[]

def command(method,params=None,session=None):
    global seq
    seq+=1; ident=seq
    payload=dict(id=ident,method=method,params=params or {})
    if session: payload['sessionId']=session
    ws.send(json.dumps(payload))
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try: event=json.loads(ws.recv())
        except websocket.WebSocketTimeoutException: continue
        if event.get('method')=='Runtime.exceptionThrown': errors.append(str(event['params']['exceptionDetails']))
        if event.get('method')=='Network.requestWillBeSent' and '/api/' in event['params']['request']['url']:
            request=event['params']['request'];request['__resourceType']=event['params'].get('type');requests.append(request)
        if event.get('method')=='Page.javascriptDialogOpening':
            seq+=1; ws.send(json.dumps(dict(id=seq,method='Page.handleJavaScriptDialog',sessionId=event['sessionId'],params=dict(accept=True))))
        if event.get('id')==ident:
            if 'error' in event: raise AssertionError(event['error'])
            return event.get('result',{})
    raise AssertionError('Timed out: '+method)
class Page:
    def __init__(self):
        self.context=command('Target.createBrowserContext')['browserContextId']
        contexts.append(self.context)
        self.target=command('Target.createTarget',dict(url='about:blank',browserContextId=self.context))['targetId']
        self.session=command('Target.attachToTarget',dict(targetId=self.target,flatten=True))['sessionId']
        for method in ['Page.enable','Runtime.enable','Network.enable']: command(method,session=self.session)
    def evaluate(self,expression):
        result=command('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True),self.session)
        if 'exceptionDetails' in result: raise AssertionError(result['exceptionDetails'])
        return result['result'].get('value')
    def navigate(self,path): command('Page.navigate',dict(url=base+path),self.session)
    def text(self): return self.evaluate('document.body?.innerText || ""')
    def wait(self,text):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if text in self.text(): return
            time.sleep(.08)
        raise AssertionError('Missing '+text+'; current page: '+self.text())
    def click(self,text):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if self.evaluate("(()=>{const e=[...document.querySelectorAll('a,button')].find(e=>e.textContent.trim()==="+json.dumps(text)+");if(!e||e.disabled)return false;e.click();return true})()"):return
            time.sleep(.05)
        raise AssertionError('Missing enabled control '+text+'; current page: '+self.text())
    def field(self,label,value):
        self.evaluate("(()=>{const l=[...document.querySelectorAll('label')].find(e=>e.textContent.trim().startsWith("+json.dumps(label)+"));if(!l)throw new Error('Missing label '+"+json.dumps(label)+");const e=l.querySelector('input,textarea,select');const proto=e instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:e instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(e,"+json.dumps(value)+");e.dispatchEvent(new Event(e instanceof HTMLSelectElement?'change':'input',{bubbles:true}))})()")
    def option(self,label,text):
        self.evaluate("(()=>{const e=[...document.querySelectorAll('label')].find(l=>l.textContent.trim().startsWith("+json.dumps(label)+")).querySelector('select');const o=[...e.options].find(o=>o.textContent.toLowerCase()==="+json.dumps(text.lower())+");if(!o)throw new Error('Missing option');e.value=o.value;e.dispatchEvent(new Event('change',{bubbles:true}))})()")
    def api(self,path,method='GET',body=None):
        return self.evaluate("(async()=>{const c=document.cookie.split(';').map(v=>v.trim()).find(v=>v.startsWith('agentconnect_csrf=')||v.startsWith('__Host-agentconnect_csrf='));const token=c?decodeURIComponent(c.slice(c.indexOf('=')+1)):'';const r=await fetch('/api/v1'+"+json.dumps(path)+",{method:"+json.dumps(method)+",credentials:'include',headers:{'Content-Type':'application/json',...(token?{'X-CSRF-Token':token}:{})},...("+json.dumps(body)+"!==null?{body:JSON.stringify("+json.dumps(body)+")}:{})});return {status:r.status,data:await r.json()}})()")
    def screenshot(self,name,mobile=False):
        command('Page.bringToFront', session=self.session)
        command('Emulation.setDeviceMetricsOverride',dict(width=390 if mobile else 1440,height=844 if mobile else 1000,deviceScaleFactor=1,mobile=mobile),self.session)
        self.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        time.sleep(.35)
        shot=command('Page.captureScreenshot',dict(format='png'),self.session)
        Path(name).write_bytes(base64.b64decode(shot['data']))

def register(page,email,company,name):
    page.navigate('/');page.wait('Welcome back');page.click('Create an account');page.wait('Create your workspace')
    page.field('Your name',name);page.field('Company name',company);page.field('Work email',email);page.field('Password','phase1-browser-password-123')
    page.click('Create workspace');page.wait('Set up your company')
    page.field('Description','A browser-verified company profile');page.field('Website','https://example.test');page.field('Industry','Commerce')
    page.click('Complete company setup');page.wait('Company dashboard')
    deadline=time.monotonic()+20
    while not page.evaluate("location.pathname==='/' && document.querySelector('h1')?.textContent==='Company dashboard'"):
        if time.monotonic()>deadline:raise AssertionError('Onboarding navigation did not finish')
        time.sleep(.05)
    me=page.api('/auth/me')['data'];assert 'token' not in me and me['user']['email']==email
    assert 'agentconnect_session' not in page.evaluate('document.cookie')
    assert page.evaluate("localStorage.getItem('agentconnect.token')") is None
    cookies=command('Storage.getCookies',dict(browserContextId=page.context))['cookies']
    session_cookie=next(cookie for cookie in cookies if cookie['name']=='agentconnect_session')
    assert session_cookie['httpOnly'] and session_cookie['sameSite']=='Lax'
    return me



def main():
    import os, sqlite3, subprocess
    (artifacts/'success.txt').write_text('Acceptance run in progress.\n')
    unique=str(time.time_ns())
    A=Page();B=Page();C=Page()
    identity_a=register(A,'p3-a-'+unique+'@example.test','Phase3 Alpha '+unique,'Alpha Reviewer')
    with sqlite3.connect(database) as fixture:
        row=fixture.execute('select id from users where email=?',(identity_a['user']['email'],)).fetchone()
        assert row and row[0]==identity_a['user']['id'], 'The API must use the same temporary SQLite file passed to --database'
    register(B,'p3-b-'+unique+'@example.test','Phase3 Beta '+unique,'Beta Reviewer')
    register(C,'p3-c-'+unique+'@example.test','Phase3 Gamma '+unique,'Gamma Reviewer')

    def check(page,label,enabled=True,legend=None):
        page.evaluate("(()=>{const scope="+("[...document.querySelectorAll('fieldset')].find(f=>f.querySelector('legend')?.textContent==="+json.dumps(legend)+")" if legend else 'document')+";const l=[...scope.querySelectorAll('label')].find(l=>l.textContent.trim().startsWith("+json.dumps(label)+"));if(!l)throw new Error('Missing checkbox');const e=l.querySelector('input[type=checkbox]');if(e.checked!=="+json.dumps(enabled)+")e.click()})()")

    def govern(page):
        page.click('Governance');page.wait('Save governance policy')
        check(page,'Participate in the company network')
        check(page,'financial claim',True,'Categories requiring approval')
        page.field('Cooldown (seconds)','0')
        page.click('Save governance policy');page.wait('Governance policy saved')
        result=page.api('/governance')['data']
        assert result['network_opt_in'] and result['policy']['allow_invitations'] and result['policy']['limits']['cooldown_seconds']==0 and 'financial_claim' in result['policy']['approval_categories']
        return result
    for p in [A,B,C]: govern(p)

    def create_agent(page,name,slug,approval=False):
        page.click('My agents');page.wait('Create agent');page.click('Create agent');page.wait('Step 1 of 7')
        for label,value in [('Agent name',name),('Agent handle',slug),('Business domain','Commerce'),('Role','Partnerships'),('Public description','Approved company collaboration agent'),('Purpose','Discuss authorized public information')]:page.field(label,value)
        page.evaluate("[...document.querySelectorAll('.builder-step')].find(e=>e.textContent.includes('Collaboration')).click()")
        page.wait('Step 4 of 7');check(page,'Allow public network publishing');check(page,'Require human approval for every reply',approval)
        page.evaluate("[...document.querySelectorAll('.builder-step')].find(e=>e.textContent.includes('Runtime')).click()")
        page.wait('Step 6 of 7');page.field('Provider','fake');page.field('Replies per agent','1');page.field('Cooldown (seconds)','0')
        page.evaluate("[...document.querySelectorAll('.builder-step')].find(e=>e.textContent.includes('Review')).click()")
        page.wait('Step 7 of 7');page.click('Save draft version');page.wait('Configuration preview')
        agent_id=int(page.evaluate('location.pathname.split("/").pop()'))
        check(page,'I have reviewed this configuration');page.click('Activate reviewed version');page.wait('Agent activated with the reviewed version')
        return agent_id
    alpha=create_agent(A,'Phase3 Alpha Agent','frontend-agent')
    beta=create_agent(B,'Phase3 Beta Agent','frontend-agent',True)
    gamma=create_agent(C,'Phase3 Gamma Agent','frontend-agent')

    # UI direct invitation and recipient acceptance must withhold prior history.
    def new_conversation(page,title,kind,agent,recipient=None):
        page.click('Conversations');page.wait('New conversation');page.click('New conversation');page.wait('Conversation type')
        page.field('Conversation type',kind);page.field('Your active agent',str(agent));page.field('Title',title)
        if recipient:page.field('Recipient agent',str(recipient))
        page.click('Create & propose invitation' if kind=='direct' else 'Create group');page.wait('Conversation history')
        return int(page.evaluate('location.pathname.split("/").pop()'))
    def send(page,text,agent):
        page.field('Send on behalf of',str(agent));page.field('Message',text);page.click('Send message');page.wait('Message sent. Agent replies appear')
    def accept(page,conversation_id):
        page.click('Conversation invitations');page.wait('Conversation invitations')
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if page.evaluate("[...document.querySelectorAll('.inbox-row')].some(e=>e.textContent.includes('Conversation #"+str(conversation_id)+"')&&[...e.querySelectorAll('button')].some(b=>b.textContent==='Accept invitation'))"):break
            time.sleep(.1)
        page.evaluate("(()=>{const row=[...document.querySelectorAll('.inbox-row')].find(e=>e.textContent.includes('Conversation #"+str(conversation_id)+"'));[...row.querySelectorAll('button')].find(b=>b.textContent==='Accept invitation').click()})()")
        page.wait('Invitation accepted')
        page.navigate('/conversations/'+str(conversation_id));page.wait('Conversation history')

    direct=new_conversation(A,'Phase3 direct '+unique,'direct',alpha,beta)
    send(A,'DIRECT BEFORE ACCEPT private history sentinel',alpha)
    accept(B,direct)
    assert 'DIRECT BEFORE ACCEPT' not in B.text()
    assert not B.api('/conversations/'+str(direct)+'/messages')['data']['items']
    A.navigate('/conversations/'+str(direct));A.wait('Conversation history');send(A,'DIRECT AFTER ACCEPT public information',alpha)
    # Use the actual independent CLI worker; no HTTP worker execution route or live model call.
    worker_env=os.environ.copy();worker_env.update(AGENTCONNECT_DATABASE_URL='sqlite:///'+database.as_posix(),AGENTCONNECT_ENABLE_FAKE='true',AGENTCONNECT_ENV='development',AGENTCONNECT_LIMITS='{"cooldown_seconds":0}',GEMINI_API_KEY='')
    for _ in range(12):
        subprocess.run([str(worker_python),'-m','app.worker','--once'],cwd=repo/'backend',env=worker_env,check=True)
        if any(row['agent_id']==beta and row['source_type']=='run_approval' for row in B.api('/governance/approvals?status=pending')['data']['items']):break
    requests_b=B.api('/governance/approvals?status=pending')['data']['items']
    reply_request=next(row for row in requests_b if row['agent_id']==beta and row['source_type']=='run_approval')
    B.navigate('/approval-center/'+str(reply_request['id']));B.wait('Proposed action');B.field('Reviewer comments','Verified public reply in the browser');B.click('Approve action');B.wait('Request status: executed')
    B.navigate('/conversations/'+str(direct));B.wait('Please review the public eligibility details before proceeding.')
    assert 'DIRECT BEFORE ACCEPT' not in B.text()
    assert B.api('/governance/approvals/'+str(reply_request['id']))['data']['reviewer_comments']=='Verified public reply in the browser'
    for _ in range(12):
        subprocess.run([str(worker_python),'-m','app.worker','--once'],cwd=repo/'backend',env=worker_env,check=True)
        if A.api('/workspace/agents/'+str(alpha)+'/activity')['data']['runs']:break

    # Human publication goes to a real governed draft and reviews through the unified center.
    def publication(page,title):
        page.click('Publications');page.wait('Create publication');page.click('Create publication');page.wait('Authoring mode')
        page.field('Title',title);page.field('Content','Guaranteed 10% annual return is proposed for human verification.');page.field('Category','financial_claim');page.field('Audience','network');page.field('Publication status','published')
        page.click('Publish update');page.wait('Review publication approval')
        publication_id=int(page.evaluate('location.pathname.split("/").pop()'))
        pub=page.api('/publications/'+str(publication_id))['data']
        assert pub['status']=='draft' and pub['approval_request_id']
        page.click('Review publication approval');page.wait('Proposed action')
        return publication_id,pub['approval_request_id']
    pub_id,pub_approval=publication(A,'Phase3 financial review '+unique)
    A.field('Reviewer comments','Approved the proposed financial statement');A.click('Approve action');A.wait('Request status: executed')
    assert A.api('/publications/'+str(pub_id))['data']['status']=='published'

    # Terminal review outcomes preserve the draft and disallow another decision.
    _,reject_id=publication(A,'Phase3 rejected '+unique)
    A.click('Reject action');A.wait('Request status: rejected')
    assert A.api('/governance/approvals/'+str(reject_id))['data']['status']=='rejected'
    _,cancel_id=publication(A,'Phase3 cancelled '+unique)
    A.click('Cancel request');A.wait('Request status: cancelled')
    assert A.api('/governance/approvals/'+str(cancel_id))['data']['status']=='cancelled'
    _,expiry_id=publication(A,'Phase3 expiry '+unique)
    # Accelerate only the isolated test fixture's 24-hour expiry; the real GET endpoint performs the transition.
    with sqlite3.connect(database) as db:
        changed=db.execute("update approval_requests set expires_at='2000-01-01 00:00:00' where id=? and company_id=?",(expiry_id,identity_a['selected_company_id'])).rowcount;assert changed==1;db.commit()
    A.navigate('/approval-center/'+str(expiry_id));A.wait('cannot be reviewed')
    assert A.api('/governance/approvals/'+str(expiry_id))['data']['status']=='expired'
    assert not A.evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent==='Approve action')")

    # A group starts with one member; invitation acceptance sets each participant's history floor.
    group=new_conversation(A,'Phase3 group '+unique,'group',alpha)
    send(A,'GROUP BEFORE ANY INVITE history sentinel',alpha)
    def invite_agent(page,recipient):
        page.field('Inviting member',str(alpha));page.field('Recipient',str(recipient));page.click('Propose invitation');page.wait('Invitation proposed')
    invite_agent(A,beta);accept(B,group)
    A.navigate('/conversations/'+str(group));A.wait('Conversation history');send(A,'GROUP BEFORE GAMMA JOIN history sentinel',alpha)
    invite_agent(A,gamma);accept(C,group)
    assert 'GROUP BEFORE' not in C.text()
    A.navigate('/conversations/'+str(group));A.wait('Conversation history');send(A,'GROUP AFTER GAMMA JOIN visible information',alpha)
    C.navigate('/conversations/'+str(group));C.wait('GROUP AFTER GAMMA JOIN visible information');assert 'GROUP BEFORE' not in C.text()
    visible=C.api('/conversations/'+str(group)+'/messages')['data']['items'];assert len(visible)==1 and visible[0]['sequence']==3
    C.navigate('/agents/'+str(gamma)+'/activity');C.wait('Agent activity');assert 'GROUP BEFORE' not in C.text()

    # Emergency pause prevents a previously pending governed action from executing.
    blocked_pub,blocked_approval=publication(C,'Phase3 pause block '+unique)
    C.click('Governance');C.wait('Pause all active agents');C.click('Pause all active agents');C.wait('Emergency pause applied')
    assert C.api('/agents/'+str(gamma))['data']['state']=='paused'
    assert C.api('/governance')['data']['policy']['emergency_paused'] is True
    C.navigate('/approval-center/'+str(blocked_approval));C.wait('Proposed action');C.click('Approve action');C.wait('Request status: blocked')
    assert C.api('/publications/'+str(blocked_pub))['data']['status']=='draft'

    # Generate real lifecycle events to exercise actual notification pagination rather than seeded metrics.
    a_agent=A.api('/agents/'+str(alpha))['data']
    for _ in range(14):
        assert A.api('/agents/'+str(alpha)+'/lifecycle','POST',dict(state='paused'))['status']==200
        assert A.api('/agents/'+str(alpha)+'/lifecycle','POST',dict(state='active',version_id=a_agent['active_version_id']))['status']==200
    A.click('Notifications');A.wait('Notifications');A.wait('Mark all as read')
    notice_page=A.api('/user-notifications?limit=25')['data'];assert notice_page['total']>25
    A.click('Next');A.wait('26–')
    A.field('Category','agent_state');A.wait('Mark read')
    A.click('Mark all as read');A.wait('Visible notifications marked as read')
    A.field('Read status','unread');A.wait('No matching notifications')
    assert A.api('/user-notifications?unread=true')['data']['total']==0
    A.field('Read status','all');A.field('Category','')
    A.click('Analytics');A.wait('Daily runs');A.field('Reporting period','7');A.wait('Daily activity data')
    analytics=A.api('/company/analytics?days=7')['data'];assert analytics['totals']['runs']>=1 and len(analytics['daily'])==7
    A.click('Audit log');A.wait('Audit log')
    audit=A.api('/audit?limit=25')['data'];assert audit['total']>0
    A.field('Event type',audit['items'][0]['event_type']);A.click('Apply filters')
    A.navigate('/agents/'+str(alpha)+'/activity');A.wait('Execution runs');assert A.api('/workspace/agents/'+str(alpha)+'/activity')['status']==200

    # Real API-backed responsive pages at 1440, 768 and 390 pixels. No expanded layout viewport can mask overflow.
    def wait_element(page,selector):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if page.evaluate('Boolean(document.querySelector('+json.dumps(selector)+'))'):return
            time.sleep(.05)
        raise AssertionError('Missing ready selector '+selector)
    for width in [1440,768,390]:
        for route,label in [('/','Company dashboard'),('/governance','Current policy' if False else 'Save governance policy'),('/approval-center','Approval center'),('/analytics','Daily runs'),('/notifications','Mark all as read'),('/audit','Apply filters')]:
            A.navigate(route);A.wait(label)
            wait_element(A,{ '/':'.usage-progress','/governance':'input[type=number]','/approval-center':'.pagination-bar','/analytics':'.trend-chart','/notifications':'.pagination-bar','/audit':'.pagination-bar'}[route])
            command('Page.bringToFront',session=A.session)
            command('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000 if width>390 else 844,deviceScaleFactor=1,mobile=width==390),A.session)
            A.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');time.sleep(.25)
            sizes=A.evaluate('({scroll:document.documentElement.scrollWidth,visual:visualViewport.width,inner:innerWidth})')
            assert sizes['scroll']<=width and sizes['visual']<=width, (width,route,sizes)
            if (width==1440 and route=='/') or (width==768 and route=='/approval-center') or (width==390 and route=='/governance'):
                shot=command('Page.captureScreenshot',dict(format='png'),A.session)
                (artifacts/('phase3-'+str(width)+'.png')).write_bytes(base64.b64decode(shot['data']))
    assert not errors, errors
    print('Phase3 REAL browser acceptance passed: three independent companies, direct and group invitation/history floors, fake CLI reply review/execution, governed publication execution/rejection/cancellation/expiry, emergency pause blocks pending publication, real notification read/category/pagination, analytics/audit/activity, 1440/768/390 layouts.')
    print('UI/API requests checked:',len(requests))
    (artifacts/'success.txt').write_text('All Phase3 browser assertions passed.\n')


if __name__=='__main__':
    try:main()
    finally:
        for context in contexts:
            try:command('Target.disposeBrowserContext',dict(browserContextId=context))
            except Exception:pass
        ws.close()

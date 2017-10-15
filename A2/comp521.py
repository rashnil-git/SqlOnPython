'''Comp521 support module with tools for downloading assignments, lecture notes, and exams
and uploading student submissions.

Gary Bishop Fall 2017
'''

import urllib
import urllib.request
import os
import os.path as osp
import json
import time
import hashlib
import pickle
import io
import random
import getpass
import inspect
import sqlite3
try:
    import Dee
    gotDee = True
except:
    gotDee = False

Site = 'https://wwwx.cs.unc.edu/Courses/comp521-f17/'
UploadSite = Site.replace('https', 'http')

#############################
#
# functions for submitting assignments
#
#############################

ATTEMPTS = 10

def fileHash(filename):
    '''Compute the checksum to be sure the file is what we expect'''
    BLOCKSIZE = 65536
    hasher = hashlib.sha1()
    with open(filename, 'rb') as fp:
        buf = fp.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = fp.read(BLOCKSIZE)
    return hasher.hexdigest()


def pushNotebook(name, uuid,
        url = 'io/submit.cgi'):
    '''Upload the notebook to our server'''

    if not name.endswith('.ipynb'):
        fname = name + '.ipynb'
    else:
        fname = name
    try:
        book = open(fname, 'rb').read()
    except IOError:
        raise UserWarning('Notebook %s not found.' % fname)
    check = fileHash(fname)
    try:
        assignment = expected['_assignment']
    except KeyError:
        raise UserWarning('Missing assignment, you must run your notebook before submitting it.')

    data = {
        'filename': name,
        'book': book,
        'token': uuid,
        'assignment': assignment,
        'check': check
    }

    postdata = urllib.parse.urlencode(data)
    postdata = postdata.encode('UTF-8') # data should be bytes
    req = urllib.request.Request(UploadSite + url, postdata)
    # try to post it to the server
    for i in range(10):
        try:
            resp = urllib.request.urlopen(req)
        except urllib.error.URLError:
            raise UserWarning('Submission failed: are you online? Make sure you have wireless on')
        except urllib.error.HTTPError as e:
            print(e)
            raise
        if resp.getcode() == 200:
            break
        time.sleep(0.1 * i)
    else:
        code = resp.getcode()
        msg = resp.read()
        raise UserWarning('upload failed code={} msg="{}"'.format(code, msg))

def showSubmitButton():
    '''Generate code to diplay the submit button in the notebook'''
    import IPython.display as ipd

    html = '''
<p>Click the button below to submit your notebook. Watch for a confirmation message
that your notebook was successfully uploaded. You may submit as often as you wish,
only the last submission will count.</p>
<button id="submitButton116">Submit this notebook</button>
<p id="submitResponse116"></p>
<script>
var site = 'SITE';
$('#submitButton116').on('click', function() {
    var site = 'SITE',
        $sresp = $('#submitResponse116'),
        button = $('#submitButton116');
    button.prop('disabled', true);
    // wait until save is complete before pushing the notebook
    $([IPython.events]).one('notebook_saved.Notebook', function() {
        // get the token by logging in
        $sresp.html('logging in');
        $.ajax({
            url: site + 'io/token/token.cgi',
            dataType: 'jsonp'
        }).done(function(data) {
            var notebook = IPython.notebook.notebook_name,
                uuid = data.token,
                command = "comp521.pushNotebook('" + notebook + "', '" + uuid + "')",
                kernel = IPython.notebook.kernel,
                handler = function (out) {
                    $('#comp116-stop-message').show();
                    if (out.content.status == "ok") {
                        $sresp.html("Successfully submitted " + notebook);
                        $('#comp116-stop-message').hide();
                    } else if(out.content.status == "error") {
                        $sresp.html(out.content.ename + ": " + out.content.evalue);
                    } else { // if output is something we haven't thought of
                        $sresp.html("[out type not implemented]")
                    }
                    button.prop('disabled', false);
                };
            $sresp.html('Submitting');
            kernel.execute(command, {shell: { reply: handler }});
        }).fail(function() {
            $sresp.html('Login failed');
            button.prop('disabled', false);
        });
    });
    // trigger the save
    $sresp.html('Saving');
    IPython.notebook.save_notebook();
});'''.replace('SITE', Site)
    return ipd.HTML(html)

##################################################
#
# functions for checking student answers
#
##################################################


def check_float(tag, given, ev, extra):
    '''Compare floats for approximate equality'''
    rtol = extra.get('relative_tolerance', 1e-5)
    atol = extra.get('absolute_tolerance', 1e-8)
    if not isinstance(given, (float, int)):
        print(tag, 'incorrect type')
        print(' expected float')
        return 0.0
    OK = abs(given - ev) < atol
    if not OK:
        print(tag, 'incorrect')
        print('  expected', ev)
    return float(OK)

def check_relation(tag, value, ev, extra):
    '''Compare Dee Relations'''
    if not isinstance(value, Dee.Relation):
        print(tag, 'incorrect type')
        #Helpful
        print('expected Dee.Relation')
        #_Helpful
        return 0.0
    OK = value == ev
    if not OK:
        print(tag, 'incorrect')
        #Helpful
        print('expected', ev)
        #_Helpful
    return float(OK)

def check_choice(tag, value, ev, extra):
    choice = extra['choice']

    if not isinstance(value, (str, unicode)):
        print(tag, 'answer should be string')
        return 0

    #Exam
    # only check the domain
    out = False
    for c in value.upper():
        if c not in choice:
            print(tag, "letter '%s' is not among the choices" % c)
            out = True
    if out:
        return 0
    return 1
    #_Exam

    # check it
    right = 0
    wrong = 0
    omitted = 0
    for c in value.upper():
        if c in ev:
            right += 1
        else:
            wrong += 1
    if len(ev) > len(value):
        omitted += len(ev) - len(value)

    # compute partial score here
    score = (right - wrong) / (right - omitted)

def listit(t):
    '''convert nested list,tuples into nested lists'''

    return list(map(listit, t)) if isinstance(t, (list, tuple)) else t

def check_list(tag, value, ev, extra):
    ev = listit(ev)
    value = listit(value)
    if 'sort' in extra:
        ev = sorted(ev)
        value = sorted(value)

    OK = (ev == value)
    if not OK:
        print(tag, 'incorrect')
        print('expected', ev)

    return float(OK)

try:
    from grading import record_grade
except ImportError:
    def record_grade(expected):
        pass

try:
    from solution import start, check, report
except ImportError:

    # contains the expected answers
    expected = {}

    def test_online():
        '''Test to see if the user is online'''
        if expected.get('_monitor', False):
            url = 'http://152.2.128.56/Courses/comp521-f17/media/monitor.txt?%s' % getpass.getuser()
            req = urllib.request.Request(url, method='HEAD')
            try:
                resp = urllib.request.urlopen(req, timeout=0.5)
                return True
            except urllib.error.URLError:
                return False
            except:
                return False
        return False

    def start(assignment):
        '''Initialize expected values for checking a student submission'''
        pname = assignment + '.pickle'
        expected.update(pickle.load(open(pname, 'rb')))
        if expected.get('_exam', False) and time.time() - osp.getmtime(pname) < 3 * 60 * 60:
            expected['_monitor'] = True
        return check, report

    def check(tag, value, *args, **kwargs):
        '''Provide feedback on a single value'''

        if test_online():
            print('\n\n**********\n\nYou appear to be online. Disable wireless before continuing!\n\n**********\n\n')

        assert tag in expected
        e = expected[tag]
            
        dv = describe_answer(value)
        score = 1.0
        
        if e['description'] != dv:
            print(tag, 'incorrect type')
            print('your answer type is', dv)
            print('expected type is', e['description'])
            score = 0.0
            
        elif 'hash' in e:
            hv = hash_answer(value, kwargs.get('precision', 5))
            if hv != e['hash']:
                score = 0.0
                print(tag, 'incorrect')
                
        else:
            ev = e['value']
            extra = e['extra']

            if gotDee and isinstance(ev, Dee.Relation):
                score = check_relation(tag, value, ev, extra)

            elif 'choice' in extra:
                score = check_choice(tag, value, ev, extra)
                if score == 0:
                    message = 'not answered'
                else:
                    message = 'answered'

            elif (isinstance(ev, (list, tuple)) and
                  isinstance(value, (list, tuple))):
                score = check_list(tag, value, ev, extra)

            elif isinstance(ev, float):
                score = check_float(tag, value, ev, extra)

            elif value == ev:
                pass

            else:
                print(tag, 'incorrect')
                print('  expected', ev)
                score = 0.0

        if score == 1.0:
            print(tag, 'appears correct')

        elif score > 0:
            print(tag, 'partially correct')

        e['correct'] = score
        
    def tagSort(tags):
        return sorted(tags,
            key=lambda tag: [ s.isdigit() and int(s) or s
                              for s in re.findall(r'\d+|\D+', tag)
                              ])

    def report(author, extra):
        '''Summarize the student's performance'''
        expected['_score'] = 0.0
        correct = 0
        problems = 0
        answered = 0
        choice = 0
        choice_points = 0
        total_choice_points = 0
        points = 0
        max_points = 0
        for tag in sorted(expected.keys()):
            if tag.startswith('_'):
                continue
            print(tag)
            problems += 1
            c = expected[tag]['correct']
            if 'choice' in expected[tag]['extra']:
                choice += 1
                if c > 0:
                    answered += 1
                    choice_points += expected[tag]['points']
                total_choice_points += expected[tag]['points']
                max_points = expected[tag]['points']
                continue

            if c > 0:
                correct += c
                points += expected[tag]['points'] * c
                if c < 1:
                    print(tag, 'partially incorrect')
            else:
                print(tag, 'incorrect')
            max_points += expected[tag]['points']
        if '_author' in expected and author == expected['_author']:
            print('You must fill in your onyen into the author variable at the top of the script')
            return
        if '_exam' in expected and expected['_exam']:
            if not extra:
                print('You must type your name as the value of the pledge variable')
                return
            else:
                print("  Pledged on my honor:", extra)
                print("   ", getpass.getuser())

        elif '_collaborators' in expected and extra == expected['_collaborators']:
            print('You must fill in the collaborators variable')
            return
        else:
            print("  Collaborators:", extra)
        print("Report for", author)
        if total_choice_points > 0:
            print("  %d of %d answered for up to %d points" % (answered, choice, choice_points))
        print("  %d of %d correct, %d of %d points" % (correct, problems-choice,
            points, max_points-total_choice_points))
        expected['_score'] = points

        record_grade(expected)

        return showSubmitButton()

from collections import OrderedDict
import re

def describe_answer(o):
    '''describe the type of an object in English'''
    def wrap(d):
        '''Enclose description in parenthesis if it contains comma or and.'''
        if ', ' in d or ' and ' in d:
            return '(' + d + ')'
        else:
            return d

    def and_list(items):
        '''comma separated list with and at the end'''
        if len(items) <= 2:
            return " and ".join(items)
        return ", ".join(items[ : -1]) + ", and " + items[-1]

    def describe_sequence(o, typ, memo):
        '''describe a list or tuple'''
        if len(o) == 0:
            return 'empty ' + typ
        if id(o) in memo:
            return '[...]'
        memo.add(id(o))
        et = [ wrap(describe_any(e, memo)) for e in o ]
        uet = list(OrderedDict.fromkeys(et))
        if len(uet) == 1:
            et = '{} {}'.format(len(et), uet[0])
        else:
            et = and_list(et)
        return typ + ' of ' + et
    
    def describe_dict(o, memo):
        if len(o) == 0:
            return 'empty dict'
        if id(o) in memo:
            return '{...}'
        memo.add(id(o))
        it = [ (describe_any(k, memo) + ':' + wrap(describe_any(v, memo))) for k,v in o.items() ]
        uit = list(OrderedDict.fromkeys(it))
        if len(uit) == 1:
            it = '{} {}'.format(len(o), uit[0])
        else:
            it = and_list(it)
        return 'dictionary of {}'.format(it)
    
    def describe_array(a):
        '''Describe a numpy array in English'''
        if issubclass(a.dtype.type, np.integer):
            t = 'integer'
        elif issubclass(a.dtype.type, np.float):
            t = 'float'
        elif issubclass(a.dtype.type, np.complex):
            t = 'complex'
        elif issubclass(a.dtype.type, np.bool_):
            t = 'boolean'
        else:
            t = str(a.dtype)
        s = ' x '.join(str(i) for i in a.shape)
        if s == '0':
            return 'empty array of ' + t
        return 'array of {} {}'.format(s, t)

    def describe_plot(o):
        '''describe a plot'''
        o = figureState(o)
        terms = []
        nlines = len(o['lines'])
        if nlines > 0:
            terms.append('{} line{}'.format(nlines, "s"[nlines==1:]))
        nbars = o['bars'].shape[-1]
        if nbars > 0:
            terms.append('{} bar{}'.format(nbars, "s"[nbars==1:]))
        for t in ['title', 'xlabel', 'ylabel']:
            if o[t]:
                terms.append(t)
        if len(terms) == 0:
            return 'empty plot'
        else:
            return 'plot with ' + and_list(terms)

    def describe_function(f):
        return 'function with %d parameter' % len(inspect.signature(f).parameters)
        
    def describe_any(o, memo):
        if isinstance(o, str):
            return 'string'
        if o is None:
            return 'None'
        if isinstance(o, list):
            return describe_sequence(o, 'list', memo)
        if isinstance(o, tuple):
            return describe_sequence(o, 'tuple', memo)
        if isinstance(o, dict):
            return describe_dict(o, memo)
        if gotDee and isinstance(o, Dee.Relation):
            return 'Dee.Relation'
        if callable(o):
            return describe_function(o)
        return str(type(o))
    
    desc = describe_any(o, set())
    def pluralize(m):
        n = int(m.group(1))
        w = m.group(3)
        if n != 1:
            if w == 'dictionary':
                w = 'dictionaries'
            else:
                w = w + 's'
        return m.group(1) + ' ' + m.group(2) + w
    desc = re.sub(r'(\d+) (\(?)(tuple|list|dictionary|integer|float|boolean|plot|parameter)', pluralize, desc)
    return desc

import hashlib

def hash_answer(o, precision=5):
    '''return a hash to represent the answer in equality tests'''
    def str_answer(o, memo):
        '''compute a hash for an answer'''
        if id(o) in memo:
            return '...'
        memo.add(id(o))
        if isinstance(o, float):
            s = 'float' + format(o, '.{}e'.format(precision))
        elif isinstance(o, (list, tuple)):
            s = str(type(o).__name__) + '(' + ','.join([str_answer(i, memo) for i in o]) + ')'
        elif isinstance(o, dict):
            s = 'dict' + str_answer(sorted(o.items()), memo)
        else:
            s = str(o)
        return s

    sa = str_answer(o, set())

    return hashlib.md5(str_answer(o, set()).encode('utf-8')).hexdigest()


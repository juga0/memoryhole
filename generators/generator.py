# -*- coding: utf-8 -*

import email.message
import sys
import os
import re
import subprocess

GPG = 'gpg'

data = {
    'txt': '''This is a test
message on multiple lines

with a silly bit more.
--
and a .sig here.
''',
    'html': '''<html>
<head>
<title>titles are usually unrendered</title>
</head>
<body>
<p>This is a test<br/>message on multiple lines</p>
<p>with a silly bit more.</p>
<hr/>
<p>and a .sig here.</p>
</body>
</html>
''',
    'bgen': ord('a')
}


def gen_boundary():
    r = chr(data['bgen']) * 12
    data['bgen'] += 1
    return r

def gen_text_plain(generator=None):
    t = email.message.Message()
    t.set_type('text/plain')
    if generator and generator.extended_description:
        t.set_payload(generator.extended_description)
    else:
        t.set_payload(data['txt'])
    del t['MIME-Version']
    return t

def gen_text_html():
    h = email.message.Message()
    h.set_type('text/html')
    h.set_payload(data['html'])
    del h['MIME-Version']
    return h

def gen_multipart_alternative(generator=None):
    s = email.message.Message()
    s.set_type('multipart/alternative')
    s.set_boundary(gen_boundary())
    s.set_payload([gen_text_plain(generator),gen_text_html()])
    del s['MIME-Version']
    return s


# adapted from notmuch:devel/printmimestructure
def render_mime_structure(z, prefix='└', stream=sys.stdout):
    '''z should be an email.message.Message object'''
    fname = '' if z.get_filename() is None else ' [' + z.get_filename() + ']'
    cset = '' if z.get_charset() is None else ' (' + z.get_charset() + ')'
    disp = z.get_params(None, header='Content-Disposition')
    if (disp is None):
        disposition = ''
    else:
        disposition = ''
        for d in disp:
            if d[0] in [ 'attachment', 'inline' ]:
                disposition = ' ' + d[0]

    if 'subject' in z:
        subject = ' (Subject: %s)' % z['subject']
    else:
        subject = ''
    if (z.is_multipart()):
        print(prefix + '┬╴' + z.get_content_type() + cset +
              disposition + fname, z.as_string().__len__().__str__()
              + ' bytes' + subject, file=stream)
        if prefix.endswith('└'):
            prefix = prefix.rpartition('└')[0] + ' '
        if prefix.endswith('├'):
            prefix = prefix.rpartition('├')[0] + '│'
        parts = z.get_payload()
        i = 0
        while (i < parts.__len__()-1):
            render_mime_structure(parts[i], prefix + '├', stream=stream)
            i += 1
        render_mime_structure(parts[i], prefix + '└', stream=stream)
        # FIXME: show epilogue?
    else:
        print(prefix + '─╴'+ z.get_content_type() + cset + disposition
                + fname, z.get_payload().__len__().__str__(),
                'bytes' + subject, file=stream)


class Generator(email.message.Message):
    def __init__(self, description, messagename, extended_description=None):
        email.message.Message.__init__(self)
        self.messagename = os.path.splitext(os.path.basename(messagename))[0]
        self.description = description
        self.extended_description = extended_description
        self.add_header('Subject', description)
        self.add_header('Message-ID',  self.messagename + '@memoryhole.example')

    def __str__(self):
        return 'E-mail generator (' + self.description + ')'


    def build_embedded_header(self):
        r = ''
        for x in ['Date', 'Subject', 'From', 'To', 'Message-ID']:
            if self.get(x):
                r += x + ': ' + self.get(x) + '\n'
        return r


    def wrap_with_header(self, body, inself=False):
        emh = email.message.Message()
        emh.set_type('text/rfc822-headers')
        emh.add_header('Content-Disposition', 'attachment')
        emh.set_payload(self.build_embedded_header())
        del emh['MIME-Version']

        if inself:
            wrapper = self
        else:
            wrapper = email.message.Message()
        wrapper.set_type('multipart/mixed')
        wrapper.set_boundary(gen_boundary())

        wrapper.set_payload([emh,body])
        del wrapper['MIME-Version']
        return wrapper

    def get_password_from(self):
        '''This returns the expected password based on the From: address'''
        return re.sub(r'.*?([^@<]*)@.*', r'_\1_', self.get('From'))

    def sign(self,body,sender=None):
        if not sender:
            sender = self.get('From')
        g = subprocess.Popen([GPG, '--batch',
                              '--homedir=corpus/OpenPGP/GNUPGHOME',
                              '--pinentry-mode=loopback',
                              '--passphrase', self.get_password_from(),
                              '--no-emit-version',
                              '--armor', '--detach-sign',
                              '--digest-algo=sha256',
                              '-u', sender],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)


        # FIXME: this is a sloppy conversion, because it would convert any thing already crlf
        # FIXME: it's also possible that this should do a conversion to string
        # form or something, instead of using raw bytes
        (sout, serr) = g.communicate(body.as_bytes().replace(b'\n', b'\r\n'))
        if serr is not None:
            sys.stderr.buffer.write(serr)

        sig = email.message.Message()
        sig.set_type('application/pgp-signature')
        sig.set_payload(sout)

        self.set_type('multipart/signed')
        self.set_param('micalg', 'pgp-sha256')
        self.set_param('protocol', 'application/pgp-signature')
        self.set_boundary(gen_boundary())
        del sig['MIME-Version']

        self.set_payload([body,sig])


    def encrypt(self,body, sign=False):
        args = [GPG, '--batch',
                '--homedir=corpus/OpenPGP/GNUPGHOME',
                '--no-emit-version',
                '--armor',
                '--compress-algo', 'none',
                '--digest-algo=sha256']
        for f in ['To', 'Cc', 'From']:
            n = self.get_all(f)
            if n:
                for x in n:
                    args += ['--recipient', '='+x]
        if sign:
            args += ['--pinentry-mode=loopback',
                     '--passphrase', self.get_password_from(),
                     '-u', self.get('From'),
                     '--sign']
        args += ['--encrypt']
        g = subprocess.Popen(args,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)

        # FIXME: this is a sloppy conversion, because it would convert any thing already crlf
        # FIXME: it's also possible that this should do a conversion to string
        # form or something, instead of using raw bytes
        (sout, serr) = g.communicate(body.as_bytes().replace(b'\n', b'\r\n'))
        if serr is not None:
            sys.stderr.buffer.write(serr)

        enc = email.message.Message()
        enc.set_type('application/pgp-encrypted')
        enc.set_payload('Version: 1')
        del enc['MIME-Version']

        data = email.message.Message()
        data.set_type('application/octet-stream')
        data.set_payload(sout)
        del data['MIME-Version']

        self.set_type('multipart/encrypted')
        self.set_param('protocol', 'application/pgp-encrypted')
        self.set_boundary(gen_boundary())

        self.set_payload([enc,data])
        self.strip_headers()

    def strip_headers(self):
        self.replace_header('Subject', 'Memory Hole Encrypted Message')
        # FIXME: anything else to strip?  for now we're just testing
        # with the Subject.

    def main(self):
        outfile = open(os.path.join('corpus',self.messagename+'.eml'), mode='w')
        if outfile:
            outfile.buffer.write(self.as_bytes())
        descstream = open(os.path.join('corpus',self.messagename+'.desc'), mode='w')
        if descstream:
            print(self.description, '\n', file=descstream)
            if self.extended_description:
                print(self.extended_description, file=descstream)
            render_mime_structure(self, stream=descstream)

"""Installer review screens. Rendering never authorizes execution."""
from install_session import review, resume_review


class InstallerModel:
    def __init__(self, selection, backend):
        self.selection = selection; self.backend = backend
        self.page = 'home'; self.message = ''; self.accepted = None

    def action(self, key):
        if self.page in ('review', 'resume'):
            if key == 'b': self.page = 'home'; self.accepted = None; return None
            if key == 'i':
                if not self.backend.available:
                    self.message = self.backend.reason; return None
                fresh = self.backend.current()
                accepted = (resume_review(self.backend.intent(), fresh) if self.page == 'resume'
                            else review(self.selection, [fresh]))
                if accepted != self.accepted:
                    self.message = 'The disk changed. Review the updated plan again.'
                    self.accepted = None; self.page = 'home'; return None
                self.page = 'progress'; return accepted
            return None
        if key == '1':
            self.accepted = review(self.selection, [self.backend.current()]); self.page = 'review'; self.message = ''
        elif key == '2':
            record = self.backend.intent()
            if record is None: self.message = 'No saved installation was found.'
            else: self.accepted = resume_review(record, self.backend.current()); self.page = 'resume'; self.message = ''
        elif key == '3': self.page = 'resources'
        elif key == 'b': self.page = 'home'; self.message = ''
        elif key == 'r': self.backend.refresh(); self.message = 'Disk metadata was reread.'
        return None

    def lines(self):
        lines = ['ONEXPLAYER 3 - SteamOS installer', '=' * 66,
                 'Media: SteamOS ' + self.selection['source']['version'] + ' / ' + self.selection['source']['build'], '']
        if self.page in ('review', 'resume'):
            a = self.accepted
            lines += [('Resume saved installation' if self.page == 'resume' else 'Review installation changes'),
                      'Target: ' + a['device'],
                      'Selected space: %.2f GiB at %.2f GiB' % (a['range']['size']/1024**3, a['range']['start']/1024**3),
                      'Keep original partitions: ' + str(len(a['protected_partitions'])),
                      'Firstboot components: ' + (', '.join(a.get('components', [])) or 'none'), '']
            for part in a['protected_partitions']:
                lines += ['  KEEP %-25s %7.2f GiB' % (part.get('name', part['node'])[:25], part['size']*512/1024**3)]
            parts = a['remaining'] if self.page == 'resume' else a['append_layout']
            if self.page == 'resume': lines += ['Already appended: ' + str(a['already_appended']) + ' partitions']
            for part in parts: lines += ['  ADD  %-25s %7.2f GiB' % (part['name'], part['size']*512/1024**3)]
            lines += ['', 'I: confirm ' + ('resume' if self.page == 'resume' else 'installation') + '    B: go back']
            if not self.backend.available: lines += ['Execution unavailable: ' + self.backend.reason]
        elif self.page == 'resources':
            lines += ['Selected public resources (not automatically installed):']
            lines += ['  ' + item for item in self.selection.get('resources', [])] or ['  none']
            lines += ['', 'Firstboot choices: ' + (', '.join(self.selection.get('components', [])) or 'none'),
                      'Carried resources do not request installation.',
                      'Compatibility and independent recovery still apply.', 'B: return to the menu']
        elif self.page == 'progress':
            lines += ['Installation in progress', self.message, '', 'C: cancel the current operation']
        elif self.page == 'result':
            lines += [self.message, '', 'Press Ctrl+Alt+Delete to return to the boot menu.']
        else:
            lines += ['1: review installation changes', '2: resume a saved installation',
                      '3: show selected resources', 'R: reread current disk metadata', '',
                      'Disk writes require a separate confirmation.']
            if not self.backend.available: lines += ['Execution unavailable: ' + self.backend.reason]
        if self.message and self.page not in ('progress', 'result'): lines += ['', self.message]
        return lines

import logging
import re
from datetime import datetime, timedelta
from dateutil.parser import parse as parsedate
from flexget.utils.titles.parser import TitleParser, ParseWarning
from flexget.utils import qualities
from flexget.utils.tools import ReList

log = logging.getLogger('seriesparser')

# Forced to INFO !
# switch to logging.DEBUG if you want to debug this class (produces quite a bit info ..)
log.setLevel(logging.INFO)

ID_TYPES = ['ep', 'date', 'sequence', 'id']


class SeriesParser(TitleParser):

    """
    Parse series.

    :name: series name
    :data: data to parse
    :expect_ep: expect series to be in season, ep format (ep_regexps)
    :expect_id: expect series to be in id format (id_regexps)
    """

    separators = '[!/+,:;|~ x-]'
    roman_numeral_re = 'X{0,3}(?:IX|XI{0,4}|VI{0,4}|IV|V|I{1,4})'
    english_numbers = ['one', 'two', 'three', 'four', 'five', 'six', 'seven',
            'eight', 'nine', 'ten']

    # Make sure none of these are found embedded within a word or other numbers
    ep_regexps = ReList([TitleParser.re_not_in_word(regexp) for regexp in [
        '(?:series|season|s)\s?(\d{1,3})(?:\s(?:.*\s)?)?(?:episode|ep|e|part|pt)\s?(\d{1,3}|%s)(?:\s?e?(\d{1,2}))?' %
            roman_numeral_re,
        '(?:series|season)\s?(\d{1,3})\s(\d{1,3})\s?of\s?(?:\d{1,3})',
        '(\d{1,2})\s?x\s?(\d+)(?:\s(\d{1,2}))?',
        '(\d{1,3})\s?of\s?(?:\d{1,3})',
        '(?:episode|ep|part|pt)\s?(\d{1,3}|%s)' % roman_numeral_re,
        'part\s(%s)' % '|'.join(map(str, english_numbers))]])
    unwanted_ep_regexps = ReList([
         '(\d{1,3})\s?x\s?(0+)[^1-9]', # 5x0
         'S(\d{1,3})D(\d{1,3})', # S3D1
         '(\d{1,3})\s?x\s?(all)', # 1xAll
         'season(?:s)?\s?\d\s?(?:&\s?\d)?[\s-]*(?:complete|full)',
         'seasons\s(\d\s){2,}',
         'disc\s\d'])
    # Make sure none of these are found embedded within a word or other numbers
    date_regexps = ReList([TitleParser.re_not_in_word(regexp) for regexp in [
        '(\d{2,4})%s(\d{1,2})%s(\d{1,2})' % (separators, separators),
        '(\d{1,2})%s(\d{1,2})%s(\d{2,4})' % (separators, separators)]])
    sequence_regexps = ReList([TitleParser.re_not_in_word(regexp) for regexp in [
        '(?:pt|part)\s?(\d+|%s)' % roman_numeral_re,
        '(\d{1,3})(?:v(?P<version>\d))?']])
    id_regexps = ReList([TitleParser.re_not_in_word(regexp) for regexp in [
        '(\d{4})x(\d+)\W(\d+)']])
    unwanted_id_regexps = ReList([
        'seasons?\s?\d{1,2}'])
    clean_regexps = ReList(['\[.*?\]', '\(.*?\)'])
    # ignore prefix regexps must be passive groups with 0 or 1 occurrences  eg. (?:prefix)?
    ignore_prefixes = [
            '(?:\[[^\[\]]*\])', # ignores group names before the name, eg [foobar] name
            '(?:HD.720p?:)',
            '(?:HD.1080p?:)']

    def __init__(self, name='', identified_by='auto', name_regexps=None, ep_regexps=None, date_regexps=None,
                 sequence_regexps=None, id_regexps=None, strict_name=False, allow_groups=None, allow_seasonless=True,
                 date_dayfirst=None, date_yearfirst=None):
        """Init SeriesParser.

        :param string name: Name of the series parser is going to try to parse.

        :param string identified_by: What kind of episode numbering scheme is expected, valid values are ep, date,
            sequence, id and auto (default).
        :param list name_regexps: Regexps for name matching or None (default), by default regexp is generated from name.
        :param list ep_regexps: Regexps detecting episode,season format. Given list is prioritized over built-in regexps.
        :param list date_regexps: Regexps detecting date format. Given list is prioritized over built-in regexps.
        :param list sequence_regexps: Regexps detecting sequence format. Given list is prioritized over built-in regexps.
        :param list id_regexps: Custom regexps detecting id format. Given list is prioritized over built in regexps.
        :param boolean strict_name: If True name must be immediately be followed by episode identifier.
        :param list allow_groups: Optionally specify list of release group names that are allowed.
        :param date_dayfirst: Prefer day first notation of dates when there are multiple possible interpretations.
        :param date_yearfirst: Prefer year first notation of dates when there are multiple possible interpretations.
        This will also populate attribute `group`.
        """

        self.name = name
        self.data = ''
        self.identified_by = identified_by
        # Stores the type of identifier found, 'ep', 'date', 'sequence' or 'special'
        self.id_type = None
        self.name_regexps = ReList(name_regexps or [])
        self.re_from_name = False
        # If custom identifier regexps were provided, prepend them to the appropriate type of built in regexps
        for mode in ID_TYPES:
            listname = mode + '_regexps'
            if locals()[listname]:
                setattr(self, listname, ReList(locals()[listname] + getattr(SeriesParser, listname)))
        self.strict_name = strict_name
        self.allow_groups = allow_groups or []
        self.allow_seasonless = allow_seasonless
        self.date_dayfirst = date_dayfirst
        self.date_yearfirst = date_yearfirst

        self.field = None
        self._reset()

    def _reset(self):
        # parse produces these
        self.season = None
        self.episode = None
        self.end_episode = None
        self.id = None
        self.id_type = None
        self.id_groups = None
        self.quality = qualities.UNKNOWN
        self.proper_count = 0
        self.special = False
        # TODO: group is only produced with allow_groups
        self.group = None

        # false if item does not match series
        self.valid = False

    def __setattr__(self, name, value):
        """
        Some conversions when setting attributes.
        `self.name` and `self.data` are converted to unicode.
        """
        if name == 'name' or name == 'data':
            if isinstance(value, str):
                value = unicode(value)
            elif not isinstance(value, unicode):
                raise Exception('%s cannot be %s' % (name, repr(value)))
        object.__setattr__(self, name, value)

    def remove_dirt(self, data):
        """Replaces some characters with spaces"""
        return re.sub(r'[_.,\[\]\(\): ]+', ' ', data).strip().lower()

    def name_to_re(self, name):
        """Convert 'foo bar' to '^[^...]*foo[^...]*bar[^...]+"""
        # TODO: Still doesn't handle the case where the user wants
        # "Schmost" and the feed contains "Schmost at Sea".
        blank = r'[\W_]'
        ignore = '(?:' + '|'.join(self.ignore_prefixes) + ')?'
        # accept either '&' or 'and'
        name = name.replace('&', '(?:and|&)')
        res = re.sub(re.compile(blank + '+', re.UNICODE), ' ', name)
        res = res.strip()
        # check for 'and' surrounded by spaces so it is not replaced within a word or from above replacement
        res = res.replace(' and ', ' (?:and|&) ')
        res = re.sub(' +', blank + '*', res, re.UNICODE)
        res = '^' + ignore + blank + '*' + '(' + res + ')' + blank + '+'
        return res

    def parse(self, data=None, field=None, quality=qualities.UNKNOWN):
        # Clear the output variables before parsing
        self._reset()
        self.field = field
        self.quality = quality
        if data:
            self.data = data
        if not self.name or not self.data:
            raise Exception('SeriesParser initialization error, name: %s data: %s' % \
               (repr(self.name), repr(self.data)))

        name = self.remove_dirt(self.name)

        # check if data appears to be unwanted (abort)
        if self.parse_unwanted(self.remove_dirt(self.data)):
            return

        log.debug('name: %s data: %s' % (name, self.data))

        # name end position
        name_start = 0
        name_end = 0

        # regexp name matching
        if not self.name_regexps:
            # if we don't have name_regexps, generate one from the name
            self.name_regexps = ReList([self.name_to_re(name)])
            self.re_from_name = True
        # try all specified regexps on this data
        for name_re in self.name_regexps:
            match = re.search(name_re, self.data)
            if match:
                if self.re_from_name:
                    name_start, name_end = match.span(1)
                else:
                    name_start, name_end = match.span()

                log.debug('NAME SUCCESS: %s matched to %s' % (name_re.pattern, self.data))
                break
        else:
            # leave this invalid
            log.debug('FAIL: name regexps %s do not match %s' % ([regexp.pattern for regexp in self.name_regexps],
                                                                 self.data))
            return

        # remove series name from raw data, move any prefix to end of string
        data_stripped = self.data[name_end:] + ' ' + self.data[:name_start]
        data_stripped = data_stripped.lower()
        log.debug('data stripped: %s' % data_stripped)

        # allow group(s)
        if self.allow_groups:
            for group in self.allow_groups:
                group = group.lower()
                for fmt in ['[%s]', '-%s']:
                    if fmt % group in data_stripped:
                        log.debug('%s is from group %s' % (self.data, group))
                        self.group = group
                        data_stripped = data_stripped.replace(fmt % group, '')
                        break
                if self.group:
                    break
            else:
                log.debug('%s is not from groups %s' % (self.data, self.allow_groups))
                return # leave invalid

        # search tags and quality if one was not provided to parse method
        if not quality or quality == qualities.UNKNOWN:
            log.debug('parsing quality ->')
            quality, remaining = qualities.quality_match(data_stripped)
            self.quality = quality
            if remaining:
                # Remove quality string from data
                log.debug('quality detected, using remaining data `%s`' % remaining)
                data_stripped = remaining

        # Remove unwanted words (qualities and such) from data for ep / id parsing
        data_stripped = self.remove_words(data_stripped, self.remove + qualities.registry.keys() +
                                                         self.codecs + self.sounds, not_in_word=True)

        data_parts = re.split('[\W_]+', data_stripped)

        for part in data_parts[:]:
            if part in self.propers:
                self.proper_count += 1
                data_parts.remove(part)
            elif part in self.specials:
                self.special = True
                data_parts.remove(part)

        data_stripped = ' '.join(data_parts).strip()

        log.debug("data for id/ep parsing '%s'" % data_stripped)

        if self.identified_by in ['ep', 'auto']:
            ep_match = self.parse_episode(data_stripped)
            if ep_match:
                # strict_name
                if self.strict_name:
                    if ep_match['match'].start() > 1:
                        return

                if ep_match['end_episode'] > ep_match['episode'] + 2:
                    # This is a pack of too many episodes, ignore it.
                    log.debug('Series pack contains too many episodes (%d). Rejecting' %
                              (ep_match['end_episode'] - ep_match['episode']))
                    return

                self.season = ep_match['season']
                self.episode = ep_match['episode']
                self.end_episode = ep_match['end_episode']
                self.id_type = 'ep'
                self.valid = True
                return

            log.debug('-> no luck with ep_regexps')

            if self.identified_by == 'ep':
                # we should be getting season, ep !
                # try to look up idiotic numbering scheme 101,102,103,201,202
                # ressu: Added matching for 0101, 0102... It will fail on
                #        season 11 though
                log.debug('expect_ep enabled')
                match = re.search(self.re_not_in_word(r'(0?\d)(\d\d)'), data_stripped, re.IGNORECASE | re.UNICODE)
                if match:
                    # strict_name
                    if self.strict_name:
                        if match.start() > 1:
                            return

                    self.season = int(match.group(1))
                    self.episode = int(match.group(2))
                    log.debug(self)
                    self.id_type = 'ep'
                    self.valid = True
                    return
                log.debug('-> no luck with the expect_ep')

        # Ep mode is done, check for unwanted ids
        if self.parse_unwanted_id(data_stripped):
            return

        # Try date mode after ep mode
        if self.identified_by in ['date', 'auto']:
            for date_re in self.date_regexps:
                match = re.search(date_re, data_stripped)
                if match:
                    # Check if this is a valid date
                    possdates = []

                    try:
                        # By default dayfirst and yearfirst will be tried as both True and False
                        # if either have been defined manually, restrict that option
                        dayfirst_opts = [True, False]
                        if self.date_dayfirst is not None:
                            dayfirst_opts = [self.date_dayfirst]
                        yearfirst_opts = [True, False]
                        if self.date_yearfirst is not None:
                            yearfirst_opts = [self.date_yearfirst]
                        kwargs_list = ({'dayfirst': d, 'yearfirst': y} for d in dayfirst_opts for y in yearfirst_opts)
                        for kwargs in kwargs_list:
                            possdate = parsedate(match.group(0), **kwargs)
                            # Don't accept dates farther than a day in the future
                            if possdate > datetime.now() + timedelta(days=1):
                                continue
                            if possdate not in possdates:
                                possdates.append(possdate)
                    except ValueError:
                        log.debug('%s is not a valid date, skipping' % match.group(0))
                        continue
                    if not possdates:
                        log.debug('All possible dates for %s were in the future' % match.group(0))
                        continue
                    possdates.sort()
                    # Pick the most recent date if there are ambiguities
                    bestdate = possdates[-1]

                    # strict_name
                    if self.strict_name:
                        if match.start() - name_end >= 2:
                            return
                    self.id = bestdate
                    self.id_groups = match.groups()
                    self.id_type = 'date'
                    self.valid = True
                    log.debug('found id \'%s\' with regexp \'%s\'' % (self.id, date_re.pattern))
                    return
            log.debug('-> no luck with date_regexps')

        # Check id regexps
        if self.identified_by in ['id', 'auto']:
            for id_re in self.id_regexps:
                match = re.search(id_re, data_stripped)
                if match:
                    # strict_name
                    if self.strict_name:
                        if match.start() - name_end >= 2:
                            return
                    self.id = '-'.join(match.groups())
                    self.id_type = 'id'
                    self.valid = True
                    log.debug('found id \'%s\' with regexp \'%s\'' % (self.id, id_re.pattern))
                    return
            log.debug('-> no luck with id_regexps')

        # Check sequences last as they contain the broadest matches
        if self.identified_by in ['sequence', 'auto']:
            for sequence_re in self.sequence_regexps:
                match = re.search(sequence_re, data_stripped)
                if match:
                    # strict_name
                    if self.strict_name:
                        if match.start() - name_end >= 2:
                            return
                    # First matching group is the sequence number
                    try:
                        self.id = int(match.group(1))
                    except ValueError:
                        self.id = self.roman_to_int(match.group(1))
                    self.season = 0
                    self.episode = self.id
                    # If anime style version was found, overwrite the proper count with it
                    if 'version' in match.groupdict():
                        if match.group('version'):
                            self.proper_count = int(match.group('version')) - 1
                    self.id_type = 'sequence'
                    self.valid = True
                    log.debug('found id \'%s\' with regexp \'%s\'' % (self.id, sequence_re.pattern))
                    return
            log.debug('-> no luck with sequence_regexps')

        # No id found, check if this is a special
        if self.special:
            # Attempt to set id as the title of the special
            self.id = data_stripped
            self.id_type = 'special'
            self.valid = True
            log.debug('found special, setting id to \'%s\'' % self.id)
            return

        raise ParseWarning('Title \'%s\' looks like series \'%s\' but I cannot find any episode or id numbering' % (self.data, self.name))

    def parse_unwanted(self, data):
        """Parses data for an unwanted hits. Return True if the data contains unwanted hits."""
        for ep_unwanted_re in self.unwanted_ep_regexps:
            match = re.search(ep_unwanted_re, data)
            if match:
                log.debug('unwanted regexp %s matched %s' % (ep_unwanted_re.pattern, match.groups()))
                return True

    def parse_unwanted_id(self, data):
        """Parses data for an unwanted id hits. Return True if the data contains unwanted hits."""
        for id_unwanted_re in self.unwanted_id_regexps:
            match = re.search(id_unwanted_re, data)
            if match:
                log.debug('unwanted id regexp %s matched %s' % (id_unwanted_re, match.groups()))
                return True

    def parse_episode(self, data):
        """
        Parses :data: for an episode identifier.
        If found, returns a dict with keys for season, episode, end_episode and the regexp match object
        If no episode id is found returns False
        """

        # search for season and episode number
        for ep_re in self.ep_regexps:
            match = re.search(ep_re, data)

            if match:
                log.debug('found episode number with regexp %s (%s)' % (ep_re.pattern, match.groups()))
                matches = match.groups()
                if len(matches) >= 2:
                    season = matches[0]
                    episode = matches[1]
                elif self.allow_seasonless:
                    # assume season 1 if the season was not specified
                    season = 1
                    episode = matches[0]
                else:
                    # Return False if we are not allowing seasonless matches and one is found
                    return False
                # Convert season and episode to integers
                try:
                    season = int(season)
                    if not episode.isdigit():
                        try:
                            idx = self.english_numbers.index(str(episode))
                            episode = 1 + idx
                        except ValueError:
                            episode = self.roman_to_int(episode)
                    else:
                        episode = int(episode)
                except ValueError:
                    log.critical('Invalid episode number match %s returned with regexp `%s`' % (match.groups(), ep_re.pattern))
                    raise
                end_episode = None
                if len(matches) == 3 and matches[2]:
                    end_episode = int(matches[2])
                    if end_episode <= episode or end_episode > episode + 10:
                        # end episode cannot be before start episode
                        # Assume large ranges are not episode packs, ticket #1271 TODO: is this the best way?
                        end_episode = None
                # Successfully found an identifier, return the results
                return {'season': season,
                        'episode': episode,
                        'end_episode': end_episode,
                        'match': match}
        return False

    def roman_to_int(self, roman):
        """Converts roman numerals up to 39 to integers"""

        roman_map = [('X', 10), ('IX', 9), ('V', 5), ('IV', 4), ('I', 1)]
        roman = roman.upper()

        # Return False if this is not a roman numeral we can translate
        for char in roman:
            if char not in 'XVI':
                raise ValueError('`%s` is not a valid roman numeral' % roman)

        # Add up the parts of the numeral
        i = result = 0
        for numeral, integer in roman_map:
            while roman[i:i + len(numeral)] == numeral:
                result += integer
                i += len(numeral)
        return result

    @property
    def identifier(self):
        """Return String identifier for parsed episode, eg. S01E02"""
        if not self.valid:
            raise Exception('Series flagged invalid')
        if self.id_type == 'ep':
            return 'S%sE%s' % (str(self.season).zfill(2), str(self.episode).zfill(2))
        elif self.id_type == 'date':
            return self.id.strftime('%Y-%m-%d')
        if self.id is None:
            raise Exception('Series is missing identifier')
        else:
            return self.id

    @property
    def proper(self):
        return self.proper_count > 0

    def __str__(self):
        # for some fucking reason it's impossible to print self.field here, if someone figures out why please
        # tell me!
        valid = 'INVALID'
        if self.valid:
            valid = 'OK'
        return '<SeriesParser(data=%s,name=%s,id=%s,season=%s,episode=%s,quality=%s,proper=%s,status=%s)>' % \
            (self.data, self.name, str(self.id), self.season, self.episode, \
             self.quality, self.proper_count, valid)

    def __cmp__(self, other):
        """Compares quality of parsers, if quality is equal, compares proper_count."""
        return cmp((self.quality, self.proper_count), (other.quality, other.proper_count))

    def __eq__(self, other):
        return self is other

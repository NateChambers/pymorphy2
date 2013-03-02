# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals, division
import os
import heapq
import collections
import logging

from pymorphy2 import opencorpora_dict
from pymorphy2 import units

logger = logging.getLogger(__name__)

_Parse = collections.namedtuple('Parse', 'word, tag, normal_form, para_id, idx, estimate, methods')

class Parse(_Parse):
    """
    Parse result wrapper.
    """

    _morph = None
    """ @type _morph: MorphAnalyzer """

    _dict = None
    """ @type _dict: Dictionary """

    def inflect(self, required_grammemes):
        res = self._morph._inflect(self, required_grammemes)
        return None if not res else res[0]

    @property
    def lexeme(self):
        """ A lexeme this form belongs to. """
        return self._morph.get_lexeme(self)

    @property
    def is_known(self):
        """ True if this form is a known dictionary form. """
        # return self.estimate == 1?
        return self._dict.word_is_known(self.word, strict_ee=True)

    @property
    def normalized(self):
        """ A :class:`Parse` instance for :attr:`self.normal_form`. """
        return self.__class__(*self.methods[-1][0].normalized(self))

    @property
    def paradigm(self):
        return self._dict.build_paradigm_info(self.para_id)


class Dictionary(object):
    """
    OpenCorpora dictionary wrapper class.
    """

    def __init__(self, path):

        logger.info("Loading dictionaries from %s", path)

        self._data = opencorpora_dict.load(path)

        logger.info("format: %(format_version)s, revision: %(source_revision)s, updated: %(compiled_at)s", self._data.meta)

        # attributes from opencorpora_dict.storage.LoadedDictionary
        self.paradigms = self._data.paradigms
        self.gramtab = self._data.gramtab
        self.paradigm_prefixes = self._data.paradigm_prefixes
        self.suffixes = self._data.suffixes
        self.words = self._data.words
        self.prediction_prefixes = self._data.prediction_prefixes
        self.prediction_suffixes_dawgs = self._data.prediction_suffixes_dawgs
        self.meta = self._data.meta
        self.Tag = self._data.Tag

        # extra attributes
        self.path = path
        self.ee = self.words.compile_replaces({'е': 'ё'})

    # ======== dictionary access methods =========

    def build_tag_info(self, para_id, idx):
        """
        Return tag as a string.
        """
        paradigm = self.paradigms[para_id]
        tag_info_offset = len(paradigm) // 3
        tag_id = paradigm[tag_info_offset + idx]
        return self.gramtab[tag_id]

    def build_paradigm_info(self, para_id):
        """
        Return a list of

            (prefix, tag, suffix)

        tuples representing the paradigm.
        """
        paradigm = self.paradigms[para_id]
        paradigm_len = len(paradigm) // 3
        res = []
        for idx in range(paradigm_len):
            prefix_id = paradigm[paradigm_len*2 + idx]
            prefix = self.paradigm_prefixes[prefix_id]

            suffix_id = paradigm[idx]
            suffix = self.suffixes[suffix_id]

            res.append(
                (prefix, self.build_tag_info(para_id, idx), suffix)
            )
        return res

    def build_normal_form(self, para_id, idx, fixed_word):
        """
        Build a normal form.
        """

        if idx == 0: # a shortcut: normal form is a word itself
            return fixed_word

        paradigm = self.paradigms[para_id]
        paradigm_len = len(paradigm) // 3

        stem = self.build_stem(paradigm, idx, fixed_word)

        normal_prefix_id = paradigm[paradigm_len*2 + 0]
        normal_suffix_id = paradigm[0]

        normal_prefix = self.paradigm_prefixes[normal_prefix_id]
        normal_suffix = self.suffixes[normal_suffix_id]

        return normal_prefix + stem + normal_suffix

    def build_stem(self, paradigm, idx, fixed_word):
        """
        Return word stem (given a word, paradigm and the word index).
        """
        paradigm_len = len(paradigm) // 3

        prefix_id = paradigm[paradigm_len*2 + idx]
        prefix = self.paradigm_prefixes[prefix_id]

        suffix_id = paradigm[idx]
        suffix = self.suffixes[suffix_id]

        if suffix:
            return fixed_word[len(prefix):-len(suffix)]
        else:
            return fixed_word[len(prefix):]


    # ======== parsing/prediction interface ============

    def parse(self, word):
        """
        Parse a word using this dictionary.
        """
        res = []
        para_normal_forms = {}
        para_data = self.words.similar_items(word, self.ee)

        for fixed_word, parses in para_data:
            # `fixed_word` is a word with proper ё letters
            for para_id, idx in parses:

                if para_id not in para_normal_forms:
                    normal_form = self.build_normal_form(para_id, idx, fixed_word)
                    para_normal_forms[para_id] = normal_form
                else:
                    normal_form = para_normal_forms[para_id]

                tag = self.build_tag_info(para_id, idx)

                parse = (fixed_word, tag, normal_form,
                         para_id, idx, 1.0,
                         ((self, fixed_word),))

                res.append(parse)

        return res

    def tag(self, word):
        """
        Tag a word using this dictionary.
        """
        para_data = self.words.similar_item_values(word, self.ee)

        # avoid extra attribute lookups
        paradigms = self.paradigms
        gramtab = self.gramtab

        # tag known word
        result = []
        for parse in para_data:
            for para_id, idx in parse:
                # result.append(self.build_tag_info(para_id, idx))
                # .build_tag_info is unrolled for speed
                paradigm = paradigms[para_id]
                paradigm_len = len(paradigm) // 3
                tag_id = paradigm[paradigm_len + idx]
                result.append(gramtab[tag_id])

        return result

    def get_lexeme(self, form, methods):
        """
        Return a lexeme (given a parsed word).
        """
        assert len(methods) == 0 or methods[0][0] is self

        fixed_word, tag, normal_form, para_id, idx, estimate, methods = form
        stem = self.build_stem(self.paradigms[para_id], idx, fixed_word)

        result = []
        for index, (_prefix, _tag, _suffix) in enumerate(self.build_paradigm_info(para_id)):
            word = _prefix + stem + _suffix

            result.append(
                (word, _tag, normal_form, para_id, index, estimate, methods)
            )

        return result

    def normalized(self, form):
        fixed_word, tag, normal_form, para_id, idx, estimate, methods = form

        if idx == 0:
            return form

        tag = self.build_tag_info(para_id, 0)
        return (normal_form, tag, normal_form,
                para_id, 0, estimate, methods)



    # ===== misc =======

    def word_is_known(self, word, strict_ee=False):
        """
        Check if a ``word`` is in the dictionary.
        Pass ``strict_ee=True`` if ``word`` is guaranteed to
        have correct е/ё letters.

        .. note::

            Dictionary words are not always correct words;
            the dictionary also contains incorrect forms which
            are commonly used. So for spellchecking tasks this
            method should be used with extra care.

        """
        if strict_ee:
            return word in self.words
        else:
            return bool(self.words.similar_keys(word, self.ee))


    def iter_known_word_parses(self, prefix=""):
        """
        Return an iterator over parses of dictionary words that starts
        with a given prefix (default empty prefix means "all words").
        """
        for word, (para_id, idx) in self.words.iteritems(prefix):
            tag = self.build_tag_info(para_id, idx)
            normal_form = self.build_normal_form(para_id, idx, word)
            parse = (word, tag, normal_form,
                     para_id, idx, 1.0,
                     ((self, word),))
            yield parse

    def __repr__(self):
        return str("<%s>") % self.__class__.__name__



class MorphAnalyzer(object):
    """
    Morphological analyzer for Russian language.

    For a given word it can find all possible inflectional paradigms
    and thus compute all possible tags and normal forms.

    Analyzer uses morphological word features and a lexicon
    (dictionary compiled from XML available at OpenCorpora.org);
    for unknown words heuristic algorithm is used.

    Create a :class:`MorphAnalyzer` object::

        >>> import pymorphy2
        >>> morph = pymorphy2.MorphAnalyzer()

    MorphAnalyzer uses dictionaries from ``pymorphy2-dicts`` package
    (which can be installed via ``pip install pymorphy2-dicts``).

    Alternatively (e.g. if you have your own precompiled dictionaries),
    either create ``PYMORPHY2_DICT_PATH`` environment variable
    with a path to dictionaries, or pass ``path`` argument
    to :class:`pymorphy2.MorphAnalyzer` constructor::

        >>> morph = pymorphy2.MorphAnalyzer('/path/to/dictionaries') # doctest: +SKIP

    By default, methods of this class return parsing results
    as namedtuples :class:`Parse`. This has performance implications
    under CPython, so if you need maximum speed then pass
    ``result_type=None`` to make analyzer return plain unwrapped tuples::

        >>> morph = pymorphy2.MorphAnalyzer(result_type=None)

    """

    ENV_VARIABLE = 'PYMORPHY2_DICT_PATH'
    DEFAULT_UNITS = [
        units.PunctuationAnalyzer,
        units.LatinAnalyzer,
        units.HyphenSeparatedParticleAnalyzer,
        units.HyphenatedWordsAnalyzer,
        units.KnownPrefixAnalyzer,
        units.UnknownPrefixAnalyzer,
        units.KnownSuffixAnalyzer,
    ]
    DEFAULT_DICTIONARY_CLASS = Dictionary

    def __init__(self, path=None, result_type=Parse, units=None,
                 dictionary_class=None):

        if dictionary_class is None:
            dictionary_class = self.DEFAULT_DICTIONARY_CLASS
        self.dictionary = dictionary_class(self.choose_dictionary_path(path))

        if result_type is not None:
            # create a subclass with the same name,
            # but with _morph attribute bound to self
            res_type = type(
                result_type.__name__,
                (result_type,),
                {'_morph': self, '_dict': self.dictionary}
            )
            self._result_type = res_type
        else:
            self._result_type = None

        # initialize units
        if units is None:
            units = self.DEFAULT_UNITS

        self._units = [cls(self) for cls in units]


    @classmethod
    def choose_dictionary_path(cls, path=None):
        if path is not None:
            return path

        if cls.ENV_VARIABLE in os.environ:
            return os.environ[cls.ENV_VARIABLE]

        try:
            import pymorphy2_dicts
            return pymorphy2_dicts.get_path()
        except ImportError:
            msg = ("Can't find dictionaries. "
                   "Please either pass a path to dictionaries, "
                   "or install 'pymorphy2-dicts' package, "
                   "or set %s environment variable.") % cls.ENV_VARIABLE
            raise ValueError(msg)


    def parse(self, word):
        """
        Analyze the word and return a list of :class:`Parse` namedtuples:

            Parse(word, tag, normal_form, para_id, idx, _estimate)

        (or plain tuples if ``result_type=None`` was used in constructor).
        """
        res = self.dictionary.parse(word)

        if not res:
            seen = set()

            for unit in self._units:
                res.extend(unit.parse(word, seen))

                if res and unit.terminal:
                    break

        if self._result_type is None:
            return res

        return [self._result_type(*p) for p in res]


    def tag(self, word):
        res = self.dictionary.tag(word)

        if not res:
            seen = set()

            for unit in self._units:
                res.extend(unit.tag(word, seen))

                if res and unit.terminal:
                    break

        return res


    def normal_forms(self, word):
        """
        Return a list of word normal forms.
        """
        seen = set()
        result = []
        for fixed_word, tag, normal_form, para_id, idx, estimate, methods in self.parse(word):
            if normal_form not in seen:
                result.append(normal_form)
                seen.add(normal_form)
        return result

    # ==== inflection ========

    def get_lexeme(self, form):
        """
        Return the lexeme this parse belongs to.
        """
        methods = form[6]
        result = methods[-1][0].get_lexeme(form, methods)
        if self._result_type is None:
            return result
        return [self._result_type(*p) for p in result]

    def _inflect(self, form, required_grammemes):
        grammemes = form[1].updated_grammemes(required_grammemes)

        possible_results = [f for f in self.get_lexeme(form)
                            if required_grammemes <= f[1].grammemes]

        def similarity(form):
            tag = form[1]
            return len(grammemes & tag.grammemes)

        return heapq.nlargest(1, possible_results, key=similarity)


    # ====== misc =========

    def iter_known_word_parses(self, prefix=""):
        """
        Return an iterator over parses of dictionary words that starts
        with a given prefix (default empty prefix means "all words").
        """
        known_parses = self.dictionary.iter_known_word_parses(prefix)
        if self._result_type is None:
            return known_parses
        return (self._result_type(*p) for p in known_parses)

    def word_is_known(self, word, strict_ee=False):
        """
        Check if a ``word`` is in the dictionary.
        Pass ``strict_ee=True`` if ``word`` is guaranteed to
        have correct е/ё letters.

        .. note::

            Dictionary words are not always correct words;
            the dictionary also contains incorrect forms which
            are commonly used. So for spellchecking tasks this
            method should be used with extra care.

        """
        return self.dictionary.word_is_known(word, strict_ee)

    @property
    def TagClass(self):
        return self.dictionary.Tag

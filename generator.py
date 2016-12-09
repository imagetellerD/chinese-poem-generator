#-*- coding: utf-8 -*-
# vim: set bg=dark noet ts=4 sw=4 fdm=indent :
	
""" Generator of Chinese Poem (宋词)"""
__author__ = 'linpingta'


import os
import sys
reload(sys)
sys.setdefaultencoding('utf8')
try:
	import ConfigParser
except ImportError:
	import configparser as ConfigParser
import logging
import re
import simplejson as json
import jieba
import jieba.posseg as pseg
from gensim import models
import random
import operator

from title_rhythm import TitleRhythmDict

basepath = os.path.abspath(os.path.dirname(__file__))


def my_unicode(lst):
	return repr(lst).decode('unicode-escape')

def my_unicode_sd(d):
	lst = [ word for (word, count) in d ]
	return my_unicode(lst)

def my_unicode_d(d):
	lst = [ word for word, count in d.iteritems() ]
	return my_unicode(lst)


class Generator(object):
	""" Generator of Chinese Poem
	"""
	def __init__(self, basepath, conf):
		self.basepath = basepath
		self._ci_words_file = os.path.join(self.basepath, conf.get('ci', 'ci_words_file'))
		self._ci_rhythm_file = os.path.join(self.basepath, conf.get('ci', 'ci_rhythm_file'))
		self._ci_result_file = os.path.join(self.basepath, conf.get('ci', 'ci_result_file'))
		self._support_titles = conf.get('ci', 'support_titles')
		
		# user input
		self._important_words = []
		self._title = ""
		self._force_data_build = False

		# load from data file
		self._title_pingze_dict = {}
		self._pingze_words_dict = {}
		self._pingze_rhythm_dict = {}
		self._rhythm_word_dict = {}
		self._reverse_rhythm_word_dict = {}
		self._reverse_pingze_word_dict = {}

		# split related data
		self._split_sentences = []
		self._word_model = None

		# word count related
		self._word_count_dict = {}
		self._rhythm_count_dict = {}

		self._bigram_word_to_start_dict = {}
		self._bigram_word_to_end_dict = {}
		self._bigram_count_dict = {}
		
		# storage of related precalculated data
		self._data_files = [
			"title_pingze_dict", "pingze_words_dict", "pingze_rhythm_dict", "rhythm_word_dict", "reverse_rhythm_word_dict", "reverse_pingze_word_dict", "word_count_dict", "rhythm_count_dict", "split_sentences", "bigram_word_to_start_dict", "bigram_word_to_end_dict", "bigram_count_dict"
		]

		# store generated poem
		self._result = ""
		# store error reason if no poem generated
		self._error_info = ""

	@property
	def important_words(self):
		return self._important_words
		
	@property
	def title(self):
		return self._title
	
	@property
	def force_data_build(self):
		return self._force_data_build

	@important_words.setter
	def important_words(self, value):
		self._important_words = value
		
	@title.setter
	def title(self, value):
		self._title = value
		
	@force_data_build.setter
	def force_data_build(self, value):
		self._force_data_build = value

	def _show_word_sentence(self, format_sentence, word_sentence, logger):
		logger.info("format_sentence %s" % my_unicode(format_sentence))
		tmp_sentence = []
		for i in range(len(format_sentence)):
			if i in word_sentence:
				tmp_sentence.append(word_sentence[i])
			else:
				tmp_sentence.append("X")
		logger.info("word_sentence %s" % my_unicode(tmp_sentence))

	def _show_word_sentences(self, format_sentences, word_sentences, logger):
		[ self._show_word_sentence(format_sentence, word_sentence, logger) for (format_sentence, word_sentence) in zip(format_sentences, word_sentences) ]

	def _build_title_pingze_dict(self, logger):
		for title, content_rhythm in TitleRhythmDict.iteritems():
			#print title
			#print content_rhythm
			#print re.split(", |. |\*|`", content_rhythm)
			sentences = re.findall(r"[0-9]+", content_rhythm)
			new_sentences = []
			for sentence in sentences:
				new_sentence = ""
				for word in sentence:
					if not int(word):
						new_sentence += "0"
					elif not (int(word) % 2):
						new_sentence += "2"
					else:
						new_sentence += "1"
				new_sentences.append(new_sentence)
			self._title_pingze_dict[title.decode()] = new_sentences

	def _build_pingze_rhythm_words_dict(self, logger):
		with open(self._ci_rhythm_file, 'r') as fp_r:
			count = 1
			while 1:
				line = fp_r.readline()
				line = line.strip().decode("utf-8")
				if not line:
					continue
				if line == "END":
					break
				if u"：" in line: # Chinese title part
					#print line
					#print len(line)
					next_line = fp_r.readline().strip().decode("utf-8")
					#print 'next', next_line
					words = []
					[ words.append(word) for word in next_line if word not in ["[", "]"] ]
					rhythm_word = line[-2]
					self._rhythm_word_dict[rhythm_word] = words

					is_ping = True
					if u"平" in line: # ping related
						self._pingze_words_dict.setdefault('1', []).extend(words)
						self._pingze_rhythm_dict.setdefault('1', []).append(rhythm_word)
						is_ping = True
					else: # ze related
						self._pingze_words_dict.setdefault('2', []).extend(words)
						self._pingze_rhythm_dict.setdefault('2', []).append(rhythm_word)
						is_ping = False

					# build reverse dict for count later
					for word in words:
						self._reverse_rhythm_word_dict[word] = rhythm_word

						if is_ping: # ping related
							self._reverse_pingze_word_dict[word] = '1'
						else: # ze related
							self._reverse_pingze_word_dict[word] = '2'

				#count += 1
				#if count > 2:
				#	break

	def _count_general_rhythm_words(self, logger):
		with open(self._ci_words_file, 'r') as fp_r:
			count = 1
			while 1:
				line = fp_r.readline()
				line = line.strip().decode("utf-8")
				if not line:
					continue
				if line == "END":
					break
				if (u"，" not in line) and (u"。" not in line): # only use content part for stats
					continue

				sentences = re.split(u"[，。]", line)
				for sentence in sentences:
					if sentence:
						final_word = sentence[-1]
						#print 'final', final_word
						if final_word not in self._reverse_rhythm_word_dict:
							#print 'not exist', final_word
							continue
						rhythm_word = self._reverse_rhythm_word_dict[final_word]
						#print 'rhythm', rhythm_word
						if final_word not in self._word_count_dict:
							self._word_count_dict[final_word] = 1
						else:
							self._word_count_dict[final_word] += 1
						if rhythm_word not in self._rhythm_count_dict:
							self._rhythm_count_dict[rhythm_word] = 1
						else:
							self._rhythm_count_dict[rhythm_word] += 1

						# build 2-gram
						for idx, word in enumerate(sentence):
							if idx >= len(sentence) - 1:
								break
							first_word = word
							second_word = sentence[idx+1]
							if (first_word == u'、') or (second_word == u'、'):
								continue
							bigram_key = '__'.join([first_word, second_word])
							if bigram_key not in self._bigram_count_dict:
								self._bigram_count_dict[bigram_key] = 1
							else:
								self._bigram_count_dict[bigram_key] += 1
							self._bigram_word_to_start_dict.setdefault(first_word, []).append(bigram_key)
							self._bigram_word_to_end_dict.setdefault(second_word, []).append(bigram_key)

				#print line
				#print 'bigram'
				#print self._bigram_count_dict
				#print self._bigram_word_to_start_dict
				#print self._bigram_word_to_end_dict

				#count += 1
				#if count > 10:
				#	break

	def _split_words(self, logger):
		""" split words with jieba"""
		with open(self._ci_words_file, 'r') as fp_r:
			count = 1
			while 1:
				line = fp_r.readline()
				line = line.strip().decode("utf-8")
				if not line:
					continue
				if line == "END":
					break
				if (u"，" not in line) and (u"。" not in line): # only use content part for stats
					continue

				#print line
				words = jieba.cut(line)
				words = list(words)
				#print '/ '.join(words)
				self._split_sentences.append(words)
				count += 1
				#if count > 10:
				#	break

	def _build_word2vec(self, logger):
		""" build word2vec for words"""
		if not self._split_words:
			logger.error("no split words, skip")
		else:
			self._word_model = models.Word2Vec(self._split_sentences, min_count=5)
			self._word_model.save(os.path.join(self.basepath, "data", "word_model"))

	def _init_data_build(self, logger):
		""" generate title, pingze, rhythm, word relationship"""
		# mapping title to ping&ze
		self._build_title_pingze_dict(logger)

		# mapping pingze, rhythm to words
		self._build_pingze_rhythm_words_dict(logger)
		
		# mapping rhythm_end to words, 
		self._count_general_rhythm_words(logger)

		## split words
		self._split_words(logger)

		## build word2vec
		self._build_word2vec(logger)

		# save related data
		for data_file in self._data_files:
			value = getattr(self, "_"+data_file)
			with open(os.path.join(self.basepath, "data", data_file), "w") as fp_w:
				json.dump(value, fp_w)

		print 'len', len(self._reverse_pingze_word_dict.keys())
		count_ping = 0
		count_ze = 0
		for key, item in self._reverse_pingze_word_dict.iteritems():
			if item == '1':
				count_ping = count_ping + 1
			if item == '2':
				count_ze = count_ze + 1
		print count_ping
		print count_ze
		

	def _load_data_build(self, logger):
		for data_file in self._data_files:
			with open(os.path.join(self.basepath, "data", data_file), "r") as fp_r:
				value = json.load(fp_r)
				setattr(self, "_"+data_file, value)
		self._word_model = models.Word2Vec.load(os.path.join(self.basepath, "data", "word_model"))

	def _get_format_with_title(self, title, logger):
		if title not in self._title_pingze_dict:
			return -1
		return self._title_pingze_dict[title]

	def _check_position_by_sentence_length(self, sentence_length, logger):
		if sentence_length == 7:
			return [0,2,4,5]
		elif sentence_length == 6:
			return [0,2,4]
		elif sentence_length == 5:
			return [0,2,4]
		elif sentence_length == 4:
			return [0,2]
		elif sentence_length == 3:
			return [0]
		else:
			return []

	def _weighted_choice(self, choices, already_check_choices=[]):
		total = sum(w for (c, w) in choices)
		r = random.uniform(0, total)
		upto = 0
		for c, w in choices:
			if upto + w >= r:
				if c not in already_check_choices:
					return c
			upto += w

	def _compare_words(self, format_words, input_words):
		for (format_word, input_word) in zip(format_words, input_words):
			if format_word == '0': # no check needed
				continue
			if format_word != input_word:
				return False
		return True

	def _combine_candidate_word_with_single_sentence(self, format_sentence, candidate_words, already_used_words, logger):
		"""
		In each sentence, put one candidate word in it
		with consideration of pingze as well as postion and already used condition
		"""
		position_word_dict = {}

		logger.info('single sentence: format_sentence %s' % my_unicode(format_sentence))
		logger.debug('single sentence: already_used_words %s' % my_unicode(already_used_words))

		# remove already used words
		logger.debug('single sentence: origin_candidate_words %s' % my_unicode(candidate_words))
		new_candidate_words = [ word for word in candidate_words if word[0] not in already_used_words ]
		logger.debug('single sentence: new_candidate_words %s' % my_unicode(new_candidate_words))
		if not new_candidate_words:
			logger.warning("use all words, that should not happen")
			new_candidate_words = candidate_words

		sentence_length = len(format_sentence)

		# chekc delimiter for sentence
		positions = self._check_position_by_sentence_length(sentence_length, logger)
		if not positions: # don't consider position, only consider pingze
			logger.info("sentence_length[%d] dont check position, as not defined" % sentence_length)

		print positions
		logger.debug("single sentence: positions %s" % str(positions))

		# random fill first
		random_already_check_words = []
		is_word_found = False
		for i in range(10):

			# randomly select one candidate word
			candidate_word = self._weighted_choice(new_candidate_words, random_already_check_words)
			if not candidate_word:
				raise ValueError("candidate_word not exist in %s" % my_unicode(new_candidate_words))
			random_already_check_words.append(candidate_word)
			logger.debug("single sentence: iter[%d] candidate_word %s" % (i, candidate_word))

			# get word pingze
			word_pingze = []
			for candidate_word_elem in candidate_word:
				if candidate_word_elem not in self._reverse_pingze_word_dict:
					break
				word_pingze.append(self._reverse_pingze_word_dict[candidate_word_elem])
			logger.debug("single sentence: iter[%d] candidate_word %s, word_pingze %s" % (i, candidate_word, my_unicode(word_pingze)))

			if len(word_pingze) != len(candidate_word):
				logger.warning("word_pingze len[%d] not equal to word len[%d]" % (len(word_pingze), len(candidate_word)))
				continue

			for j in range(len(positions) - 1): # dont check rhythm part
				pos_start = positions[j]
				pos_end = positions[j+1]
				tmp_word = format_sentence[pos_start:pos_end] 
				logger.debug('iter[%d] pos_iter[%d] word_pingze %s, tmp_word %s' % (i, j, word_pingze, tmp_word))
				if (len(tmp_word) == len(word_pingze)) and (self._compare_words(tmp_word, word_pingze)):
					# write word with position
					for p, m in enumerate(range(pos_start, pos_end)):
						position_word_dict[m] = candidate_word[p]
					is_word_found = True
					break

			if is_word_found:
				already_used_words.append(candidate_word)
				logger.info("single sentence: add candidate_word %s to word_sentence" % candidate_word)
				break

		return position_word_dict

	def _filter_simliar_words(self, whole_similar_words, logger):
		filtered_similar_words = []
		for (word, similarity) in whole_similar_words:
			logger.debug("word[%s] len[%d]" % (word, len(word)))

			word_elems = pseg.cut(word)
			word_flag_valid = False
			for word_elem, flag in word_elems:
				logger.debug("word[%s] word_elem[%s] flag[%s]" % (word, word_elem, flag))
				if flag in ['n', 'ns', 'nr', 't']:
					word_flag_valid = True
					break
				
			if len(word) < 2 and (not word_flag_valid):
				continue

			filtered_similar_words.append((word, similarity))
		return filtered_similar_words

	def _combine_important_word_with_sentence(self, important_words, format_sentences, logger):
		""" 
		make every sentence has one related importanct word
		and promise pingze order as well as position order

		we try to use whole word to find similar words first,
		if not, then use each word to find
		"""
		word_sentences = []

		sentence_length = len(format_sentences)
		candidate_length = 5 * sentence_length

		# if put all words in word2vec.most_similar function, and any one of words not exist will lead to call fail
		# so try to check all words and get most common valid words, ugly but seems no official func given
		useful_important_words = []
		for important_word in important_words:
			try:
				similar_words = self._word_model.most_similar(positive=[ important_word ], topn=candidate_length)
			except KeyError as e1:
				pass
			else:
				useful_important_words.append(important_word)

		# trick here if no useful word given
		if not useful_important_words:
			useful_important_words = [u"菊花"]

		whole_similar_words = []
		try:
			whole_similar_words = self._word_model.most_similar(positive=useful_important_words, topn=candidate_length)
			logger.info("get whole_similar_words %s based on important_words %s as whole" % (my_unicode(whole_similar_words), my_unicode(important_words)))
		except KeyError as e:
			logger.exception(e)

		# Oops, we don't know what user want, create one randomly
		if not whole_similar_words:
			logger.warning("Oops, no similar word generated based on important_word[%s] seperately" % str(important_word))
		else:
			# filter word type and word length
			whole_similar_words = self._filter_simliar_words(whole_similar_words, logger)
			logger.info("filtered whole_similar_words %s based on important_words %s as whole" % (my_unicode(whole_similar_words), my_unicode(important_words)))

			# order list of tuple, and fetch the first candidate_length of candidates
			whole_similar_words = sorted(whole_similar_words, key=operator.itemgetter(1), reverse=True)
			candidate_words = whole_similar_words[:candidate_length]
			logger.info("get candidate_words %s based on important_words %s" % (my_unicode(candidate_words), my_unicode(important_words)))

		# at now, we promise whole_similar_words have enough data
		# now, combine them with sentences
		already_used_words = []
		for format_sentence in format_sentences:
			word_sentence = self._combine_candidate_word_with_single_sentence(format_sentence, candidate_words, already_used_words, logger)
			word_sentences.append(word_sentence)

		return word_sentences

	def _generate_common_rhythm(self, is_ping=True):
		""" generate common rhythm"""

		candidate_rhythms = self._pingze_rhythm_dict["1"] if is_ping else self._pingze_rhythm_dict["2"]
		#print 'rhythm_count', self._rhythm_count_dict

		candidate_rhythm_count_dict = {}
		for candidate_rhythm in candidate_rhythms:
			if candidate_rhythm in self._rhythm_count_dict:
				candidate_rhythm_count_dict[candidate_rhythm] = self._rhythm_count_dict[candidate_rhythm]

		candidate_rhythm_count_dict = sorted(candidate_rhythm_count_dict.items(), key=operator.itemgetter(1), reverse=True)
				
		count = 0
		narrow_candidate_rhythms = []
		for (rhythm, rhythm_count) in candidate_rhythm_count_dict:
			narrow_candidate_rhythms.append((rhythm, rhythm_count))
			count = count + 1
			if count > 5:
				break

		print 'narrow' , narrow_candidate_rhythms
		selected_rhythm = self._weighted_choice(narrow_candidate_rhythms)
		print 'select', selected_rhythm
		return selected_rhythm

	def _generate_common_words(self, rhythm, is_ping=True):
		""" generate common words"""

		candidate_words = self._rhythm_word_dict[rhythm]

		candidate_word_count_dict = {}
		for candidate_word in candidate_words:
			if candidate_word in self._word_count_dict:
				candidate_word_count_dict[candidate_word] = self._word_count_dict[candidate_word]

		candidate_word_count_dict = sorted(candidate_word_count_dict.items(), key=operator.itemgetter(1), reverse=True)
		return candidate_word_count_dict

	def _generate_common_rhythm_words(self, is_ping, logger):
		""" generate rhythm words
		first, generate common rhythm
		second, generate words based on rhythm
		"""

		logger.info("generate_rhythm: generate common rhythm for isping[%d]" % int(is_ping))
		rhythm = self._generate_common_rhythm(is_ping)
		logger.info("generate_rhythm: use rhythm[%s] for is_ping[%d] generatoin" % (rhythm, int(is_ping)))
		logger.info("generate_rhythm: generate common words for isping[%d]" % int(is_ping))
		word_count_dict = self._generate_common_words(rhythm, is_ping)
		logger.info("generate_rhythm: word_count_dict %s for isping[%d]" % (my_unicode_sd(word_count_dict), int(is_ping)))
		return word_count_dict

	def _generate_rhythm(self, format_sentences, word_sentences, logger):
		""" generate rhythm"""
		
		logger.info("generate_rhythm: format_sentences")

		# generate ping word with count
		ping_word_count_dict = self._generate_common_rhythm_words(True, logger)

		# genrate ze word with count
		ze_word_count_dict = self._generate_common_rhythm_words(False, logger)

		already_used_rhythm_words = []
		for format_sentence, word_sentence in zip(format_sentences, word_sentences):
			logger.info("generate_rhythm: format_sentence %s, word_sentence %s" % (my_unicode(format_sentence), my_unicode(word_sentence)))
			rhythm_word = ""
			if format_sentence[-1] == '1':
				rhythm_word = self._weighted_choice(ping_word_count_dict, already_used_rhythm_words)
			elif format_sentence[-1] == '2':
				rhythm_word = self._weighted_choice(ze_word_count_dict, already_used_rhythm_words)
			elif format_sentence[-1] == '0':
				rhythm_word = self._weighted_choice(ping_word_count_dict + ze_word_count_dict, already_used_rhythm_words)
			else:
				logger.error("rhythm_type[%s] illegal" % format_sentence[-1])
			already_used_rhythm_words.append(rhythm_word)
			logger.debug("generate_rhythm: use rhythm_word %s" % rhythm_word)

			word_sentence[len(format_sentence)-1] = rhythm_word
				
	def _fill_word(self, direction, tofill_position, format_sentence, word_sentence, global_repeat_words, logger):
		""" fill word by related word, and position"""

		print 'tofill_position_in_fill_word', tofill_position
		seed_word = word_sentence[tofill_position - direction]
		print 'seed_word', seed_word

		# check 2-gram dict and pingze order
		if direction > 0:
			bigram_word_dict = self._bigram_word_to_start_dict
			verb_position = -1
		else:
			bigram_word_dict = self._bigram_word_to_end_dict
			verb_position = 0

		print 'verb_position', verb_position

		if seed_word in bigram_word_dict:
			candidate_words = bigram_word_dict[seed_word]
			candidate_verb_count_dict = {}
			for candidate_word in candidate_words:

				#print 'verb_candidate_word', candidate_word
				candidate_verb = candidate_word[verb_position]
				#print 'verb_candidate_verb', candidate_verb
				if candidate_verb not in self._reverse_pingze_word_dict:
					continue

				# not use repeated word
				if candidate_verb in global_repeat_words:
					continue

				# check pingze order first
				if (format_sentence[tofill_position] != '0') and (self._reverse_pingze_word_dict[candidate_verb] != format_sentence[tofill_position]):
					continue

				# set initial, protect not exists
				candidate_verb_count_dict[candidate_verb] = 1
				if candidate_word in self._bigram_count_dict:
					candidate_verb_count_dict[candidate_verb] = self._bigram_count_dict[candidate_word]

			if candidate_verb_count_dict: # there exists some valid verb
				selected_word = ""
				max_count = -1
				for candidate_verb, count in candidate_verb_count_dict.iteritems():
					if count > max_count:
						max_count = count
						selected_word = candidate_verb
			else:
				print 'visit2'
				if candidate_words: # no pingze satisfy, random select one
					idx = random.randint(0, len(candidate_words))
					selected_word = candidate_words[idx][verb_position]
				else:
					raise ValueError("word exist in bigram_word_dict, but it's empty")
		else: # word not exists in 2-gram
			pass

		# select and fill
		word_sentence[tofill_position] = selected_word

		print 'fill', tofill_position, selected_word, word_sentence

	def _sub_generate(self, format_sentence, word_sentence, global_repeat_words, logger, level=0):
		""" recursion generate"""

		print 'current level', level

		sentence_length = len(format_sentence)
		print 'len word_sentence', len(word_sentence.keys()), sentence_length

		# all position filled, return
		if len(word_sentence.keys()) == sentence_length:
			print 'recursion finish'
			return

		# show candidate positions based on current filled positions
		candidate_positions = []
		[ candidate_positions.append(i) for i in range(sentence_length) if ((i-1) in word_sentence) or ((i+1) in word_sentence) ]
		if not candidate_positions:
			raise ValueError("candidation_position len zero")
		if len(candidate_positions) == 1:
			tofill_position = candidate_positions[0]
		else: # random choose one
			idx = random.randint(0, len(candidate_positions) - 1)
			tofill_position = candidate_positions[idx]

		print 'candidate_positions', candidate_positions
		print 'tofill_positoin', tofill_position

		up_fill_direction = (tofill_position - 1) in word_sentence
		down_fill_direction = (tofill_position + 1) in word_sentence
		both_fill_direction = up_fill_direction and down_fill_direction

		if both_fill_direction: # consider format, choose only one, consider later
			up_fill_direction = False

		both_fill_direction = up_fill_direction and down_fill_direction
		assert (not both_fill_direction)

		# fill word one by one
		if up_fill_direction:
			print 'up_fill'
			self._fill_word(1, tofill_position, format_sentence, word_sentence, global_repeat_words, logger)
		else:
			print 'down_fill'
			self._fill_word(-1, tofill_position, format_sentence, word_sentence, global_repeat_words, logger)
	
		level = level + 1
		self._sub_generate(format_sentence, word_sentence, global_repeat_words, logger, level)

	def _generate(self, format_sentences, word_sentences, logger):
		""" generate poem based on important words and rhythm word"""

		# generate each sentence
		global_repeat_words = []
		test_sentence = ""
		for (format_sentence, word_sentence) in zip(format_sentences, word_sentences):
			print 'final'
			print format_sentence
			print word_sentence

			self._sub_generate(format_sentence, word_sentence, global_repeat_words, logger)
			self._show_word_sentence(format_sentence, word_sentence, logger)
			[ global_repeat_words.append(word) for word in word_sentence.values() ]

			print 'final_fill'
			print word_sentence
			for word in word_sentence.values():
				test_sentence += word
			test_sentence += ","
		return test_sentence

	def init(self, logger):

		if self._force_data_build:
			self._init_data_build(logger)
		else:
			try:
				self._load_data_build(logger)
			except Exception as e:
				logger.exception(e)
				self._init_data_build(logger)
	
	def check(self, input_param_dict, logger):
		if ('title' in input_param_dict) and (input_param_dict['title'] not in self._support_titles):
			return "%s 不是候选的词牌名" % input_param_dict['title']

	def generate(self, logger):
		""" main function for poem generated"""

		# get title related sentences
		format_sentences = self._get_format_with_title(self._title, logger)
		if format_sentences < 0:
			raise ValueError("title[%s] not defined in dict" % self._title)

		# combine important words with format sentences
		word_sentences = self._combine_important_word_with_sentence(self._important_words, format_sentences, logger)
		self._show_word_sentences(format_sentences, word_sentences, logger)

		# decide rhythm and related words
		self._generate_rhythm(format_sentences, word_sentences, logger)
		self._show_word_sentences(format_sentences, word_sentences, logger)

		# now, generate poem
		return self._generate(format_sentences, word_sentences, logger)


if __name__ == '__main__':
	confpath = os.path.join(basepath, 'conf/poem.conf')
	conf = ConfigParser.RawConfigParser()
	conf.read(confpath)
	logging.basicConfig(filename=os.path.join(basepath, 'logs/chinese_poem.log'), level=logging.DEBUG,
		format = '[%(filename)s:%(lineno)s - %(funcName)s %(asctime)s;%(levelname)s] %(message)s',
		datefmt = '%a, %d %b %Y %H:%M:%S'
	)
	logger = logging.getLogger('ChinesePoem')
 
	generator = Generator(basepath, conf)
	try:
		# As user input, for theme of poem, and title
		#user_input_dict = dict(title=u"浣溪沙", important_words=[u"菊花", u"庭院"], force_data_build=False)
		#user_input_dict = dict(title=u"水调歌头", important_words=[u"菊花", u"院子"], force_data_build=False)
		#user_input_dict = dict(title=u"南乡子", important_words=[u"菊花", u"院子"], force_data_build=False)
		user_input_dict = dict(title=u"浣溪沙", important_words=[u"菊花", u"院子"], force_data_build=False)
		#user_input_dict = dict(title=u"浣溪沙", important_words=[u"菊", u"院子"], force_data_build=False)
		print user_input_dict["title"]

		# Init
		generator.force_data_build = user_input_dict["force_data_build"]
		generator.init(logger)

		# Generate poem
		error_info = generator.check(user_input_dict, logger)
		if not error_info:
			generator.important_words = user_input_dict["important_words"]
			generator.title = user_input_dict["title"]

			logger.info("generate poem for title %s, with important words %s" % (generator.title, my_unicode(generator.important_words)))
			print generator.generate(logger)
		else:
			logger.error("dont generate poem because of %s" % error_info)
			print error_info
		   
	except ValueError as e:
		logger.exception(e)
		print e
	except Exception as e:
		logger.exception(e)
		print e


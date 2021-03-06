import re
import copy
import json
import arrow
import datetime

# Elasticsearch libraries, certifi required by Elasticsearch
import elasticsearch
from elasticsearch_dsl import Search
from elasticsearch_dsl.query import Q
from elasticsearch_dsl.connections import connections
import certifi

from common import Message, utils
import config
from config.es_config import ES_COURSE_INDEX_PREFIX, ES_FCE_INDEX


##
# @brief      The Searcher object that parses input and generates queries.
##
class Searcher(object):
    _doc_type = None
    _default_size = 5

    #
    # @brief      init
    #
    # @param      self       The object
    # @param      raw_query  The raw query
    # @param      index      The index
    # @param      size       The size
    # @param      sort       sort is either None or a list
    #
    def __init__(self, raw_query, index=None, size=_default_size, sort=None):
        self.raw_query = copy.deepcopy(raw_query)
        self.index = index
        self.size = size
        self.doc_type = self._doc_type
        self.sort = sort

    def __repr__(self):
        return "<Searcher Object: raw_query={}>".format(repr(self.raw_query))

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    def execute(self):
        response = self.fetch(self.generate_query(), self.index,
                              size=self.size, doc_type=self.doc_type,
                              sort=self.sort)
        # if config.settings.DEBUG:
        #     print("[DEBUG] ES response:")
        #     print(json.dumps(response.to_dict(), indent=2))
        return response

    @staticmethod
    def fetch(query, index, size=5, doc_type=None, sort=None):
        s = Search(index=index, doc_type=doc_type).query(query).extra(size=size)
        if sort:
            s = s.sort(*sort)
        try:
            response = s.execute()
        except elasticsearch.exceptions.NotFoundError as e:
            # print(formatErrMsg(e, "ES"))
            response = e.info
        except elasticsearch.exceptions.RequestError as e:
            # print(formatErrMsg(e, "ES"))
            response = e.info
        except elasticsearch.exceptions.TransportError as e:
            # print(formatErrMsg(e, "ES"))
            response = e.info

        return response

    ##
    # @brief      Generate the query for the database.
    ##
    # @return     (dict) The query for querying the database.
    ##
    def generate_query(self):
        query = Q()
        return query


class FCESearcher(Searcher):
    _doc_type = 'fce'
    _default_size = 5

    def __init__(self, raw_query, index=None, size=_default_size, sort=None):
        super().__init__(raw_query, index=index, size=size, sort=sort)

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    def generate_query(self):
        raw_query = self.raw_query
        query = Q()

        if 'courseid' in raw_query:
            courseid = raw_query['courseid'][0]
            query &= Q('term', courseid=courseid)

        if 'instructor' in raw_query:
            instructor = raw_query['instructor'][0]
            query &= Q('match', instructor={'query': instructor, 'operator': 'and'})

        if config.settings.DEBUG:
            print(json.dumps(query.to_dict(), indent=2))
            print("[DEBUG] max size: {}, index: {}".format(self.size, self.index))
        return query


class CourseSearcher(Searcher):
    _doc_type = 'course'
    _default_size = 5

    def __init__(self, raw_query, index=None, size=_default_size):
        super().__init__(raw_query, index, size)

    @property
    def index(self):
        return self._index

    # @brief      Sets the index from short representation of a term. e.g. f17
    #               To the ES index
    @index.setter
    def index(self, value):
        if value is None:
            # Everything
            self._index = ES_COURSE_INDEX_PREFIX + '*'
        elif value == 'current':
            # Current semester
            self._index = utils.get_current_course_index()
        elif re.match('^(f|s|m1|m2)\d{2}$', value):
            # Match a semester, e.g. f17 or m217
            self._index = ES_COURSE_INDEX_PREFIX + value
        else:
            # Unknown index, use as is
            self._index = value

    def generate_query(self):
        raw_query = self.raw_query
        query = Q()

        # TODO: use the English analyser.
        # TODO BUG: text and courseid presented in the same time would cause
        # empty return value
        if 'text' in raw_query:
            text = raw_query['text'][0]
            text_query = Q('bool',
                           should=[
                               Q('match', name=text),
                               Q('match', desc=text)
                           ]
                           )
            query &= text_query

        else:
            if 'name' in raw_query:
                name = raw_query['name'][0]
                name_query = Q('bool',
                               must=Q('match', name=name)
                               )
                query &= name_query
            if 'desc' in raw_query:
                desc = raw_query['desc'][0]
                desc_query = Q('bool',
                               must=Q('match', desc=desc)
                               )
                query &= desc_query

        if 'courseid' in raw_query:
            courseid = raw_query['courseid'][0]
            if self.index is None:
                current_semester = utils.get_semester_from_date(
                    datetime.datetime.today())
                id_query = Q('bool',
                             must=Q('term', id=courseid),
                             should=Q('match', semester=current_semester)
                             )
            else:
                id_query = Q('term', id=courseid)
            query &= id_query

        # Declare the variables to store the temporary nested queries
        lec_nested_queries = {}
        sec_nested_queries = {}
        lec_name_query = Q()
        sec_name_query = Q()

        if 'instructor' in raw_query:
            instructor = " ".join(raw_query['instructor'])
            _query_obj = {'query': instructor,
                          'operator': 'and'}
            if 'instructor_fuzzy' in raw_query:
                _query_obj['fuzziness'] = 'AUTO'

            lec_name_query = Q('match',
                               lectures__instructors=_query_obj)
            sec_name_query = Q('match',
                               sections__instructors=_query_obj)

        # TODO: check if DH 100 would give DH 2135 and PH 100
        # see if multilevel nesting is needed
        if 'building' in raw_query:
            building = raw_query['building'][0].upper()
            lec_building_query = Q('match', lectures__times__building=building)
            sec_building_query = Q('match', sections__times__building=building)
            lec_nested_queries['lec_building_query'] = lec_building_query
            sec_nested_queries['sec_building_query'] = sec_building_query

        if 'room' in raw_query:
            room = raw_query['room'][0].upper()
            lec_room_query = Q('match', lectures__times__room=room)
            sec_room_query = Q('match', sections__times__room=room)
            lec_nested_queries['lec_room_query'] = lec_room_query
            sec_nested_queries['sec_room_query'] = sec_room_query

        if 'datetime' in raw_query:
            # Get day and time from the datetime object
            # raw_query['datetime'] is of type [arrow.arrow.Arrow]
            date_time = raw_query['datetime'][0].to('America/New_York')
            day = date_time.isoweekday() % 7
            time = date_time.time().strftime("%I:%M%p")
            delta_time = datetime.timedelta(minutes=raw_query['timespan'][0])
            shifted_time = (date_time + delta_time).time().strftime("%I:%M%p")

            # NOTE: Known bug: if the time spans across two days, it would
            # give a wrong result because day is calculated based
            # on the begin time

            # Construct the query based on day and time
            _times_begin_query = {'lte': shifted_time, 'format': 'hh:mma'}
            _times_end_query = {'gt': time, 'format': 'hh:mma'}

            lec_time_query = Q('bool', must=[Q('match', lectures__times__days=day),
                                             Q('range', lectures__times__begin=_times_begin_query),
                                             Q('range', lectures__times__end=_times_end_query)])
            sec_time_query = Q('bool', must=[Q('match', sections__times__days=day),
                                             Q('range', sections__times__begin=_times_begin_query),
                                             Q('range', sections__times__end=_times_end_query)])
            lec_nested_queries['lec_time_query'] = lec_time_query
            sec_nested_queries['sec_time_query'] = sec_time_query

        # Combine all the nested queries
        _lec_temp = Q()
        _sec_temp = Q()
        for key, value in lec_nested_queries.items():
            if _lec_temp is None:
                _lec_temp = value
            else:
                _lec_temp &= value

        for key, value in sec_nested_queries.items():
            if _sec_temp is None:
                _sec_temp = value
            else:
                _sec_temp &= value

        combined_lec_query = Q('nested',
                               query=(
                                   Q('nested',
                                     query=(_lec_temp),
                                     path='lectures.times') &
                                   lec_name_query
                               ),
                               path='lectures',
                               inner_hits={}
                               )
        combined_sec_query = Q('nested',
                               query=(
                                   Q('nested',
                                     query=(_sec_temp),
                                     path='sections.times') &
                                   sec_name_query),
                               path='sections',
                               inner_hits={}
                               )
        # And finally combine the lecture query and section query with "or"
        query &= Q('bool', must=[combined_lec_query | combined_sec_query])

        if config.settings.DEBUG:
            print(json.dumps(query.to_dict(), indent=2))
            print("[DEBUG] max size: {}".format(self.size))
        return query


# @brief  Initializes connection to the Elasticsearch server
#         The settings are in config/es_config.py
def init_es_connection():
    if config.es_config.SERVICE == 'AWS':
        from elasticsearch import RequestsHttpConnection
        from requests_aws4auth import AWS4Auth
        from config.es_config import AWS_ES_HOSTS, AWS_ACCESS_KEY,\
                                     AWS_SECRET_KEY, AWS_REGION
        awsauth = AWS4Auth(AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION, 'es')
        connections.create_connection(
            hosts=AWS_ES_HOSTS,
            http_auth=awsauth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection
        )
    else:
        from config.es_config import ES_HOSTS, ES_HTTP_AUTH
        connections.create_connection(
            hosts=ES_HOSTS,
            timeout=20,
            use_ssl=True,
            verify_certs=True,
            http_auth=ES_HTTP_AUTH
        )


# @brief  Initializes an output dictionary for "courses" endpoint
def init_courses_output():
    output = {'response': {},
              'courses': []}
    return output


# @brief  Formats the output for the courses endpoint
def format_courses_output(response):
    output = init_courses_output()
    output['response'] = response_to_dict(response)

    if has_error(response):
        return output
    for hit in response:
        output['courses'].append(hit.to_dict())

    return output


def init_fces_output():
    output = {'response': {},
              'fces': []}
    return output


def format_fces_output(response):
    output = init_fces_output()
    output['response'] = response_to_dict(response)

    if has_error(response):
        return output
    for hit in response:
        output['fces'].append(hit.to_dict())

    return output


def has_error(response):
    if isinstance(response, dict) and response.get('status') is not None:
        return True
    return False


def response_to_dict(response):
    if isinstance(response, dict):
        return response
    else:
        if config.settings.DEBUG:
            print("[DEBUG] hits count: {}".format(response.hits.total))
        return response.to_dict()


#
#
# @brief      Get the course by courseid.
#
# @param      courseid  (str) The courseid
# @param      term      (str) The elasticsearch index
#
# @return     A dictionary {course: [<dictionary containing the course info>],
#             response: <response from the server> }
#
def get_course_by_id(courseid, term=None):
    output = {'response': {},
              'course': None}
    index = term

    if re.search("^\d\d-\d\d\d$", courseid):
        searcher = CourseSearcher({'courseid': [courseid]}, index=index)
        response = searcher.execute()
        output['response'] = response_to_dict(response)

        if has_error(response):
            return output
        if response.hits.total != 0:
            # Got some hits
            output['course'] = response[0].to_dict()

    return output


def get_courses_by_id(courseid):
    output = init_courses_output()

    if re.search("^\d\d-\d\d\d$", courseid):
        searcher = CourseSearcher({'courseid': [courseid]}, index=None)
        response = searcher.execute()
        output = format_courses_output(response)
        if len(output['courses']) == 0:
            output['response']['status'] = 404

    return output


#
#
# @brief      Get the course by instructor name.
#
# @param      name      (str) The instructor name
# @param      index     (str) The elasticsearch index
#
# @return     A dictionary {courses: [<dictionary containing the course info>],
#             response: <response from the server> }
#
def get_courses_by_instructor(name, fuzzy=False, index=None, size=100):
    raw_query = {'instructor': [name]}
    if fuzzy:
        raw_query['instructor_fuzzy'] = [name]

    searcher = CourseSearcher(raw_query, index=index, size=size)
    response = searcher.execute()
    output = format_courses_output(response)
    return output


def get_courses_by_building_room(building, room, index=None, size=100):
    assert(building is not None or room is not None)
    raw_query = dict()
    if building is not None:
        raw_query['building'] = [building]
    if room is not None:
        raw_query['room'] = [room]
    searcher = CourseSearcher(raw_query, index=index, size=size)
    response = searcher.execute()
    output = format_courses_output(response)
    return output


def get_courses_by_datetime(datetime_str, span_str=None, size=200):
    span_minutes = 0
    if span_str is not None:
        try:
            span_minutes = int(span_str)
            if not (config.course.SPAN_LOWER_LIMIT <= span_minutes <=
                    config.course.SPAN_UPPER_LIMIT):
                raise(Exception(Message.SPAN_PARSE_FAIL))
        except:
            output = init_courses_output()
            output['response'] = {
                'status': 400,
                'error': {
                    'message': Message.SPAN_PARSE_FAIL
                }
            }
            return output

    try:
        # Try to convert the input string into arrow datetime format
        # if the string is 'now', then set time to current time
        if datetime_str == 'now':
            date_time = arrow.now()
        else:
            date_time = arrow.get(datetime_str)
    except:
        output = init_courses_output()
        output['response'] = {
            'status': 400,
            'error': {
                'message': Message.DATETIME_PARSE_FAIL
            }
        }
        return output

    index = utils.get_course_index_from_date(date_time.datetime)
    searcher = CourseSearcher(
        {'datetime': [date_time],
         'timespan': [span_minutes]},
        index=index, size=size
    )
    response = searcher.execute()
    output = format_courses_output(response)
    return output


def get_courses_by_searching(args, size=100):
    # valid_args = ('text', 'name', 'desc', 'instructor', 'courseid',
    # 'building', 'room', 'datetime_str', 'span_str', 'term')

    if len(args) == 0:
        output = init_courses_output()
        output['response'] = {
            'status': 400,
            'error': {
                'message': Message.EMPTY_SEARCH
            }
        }
        return output

    raw_query = {}
    if 'text' in args:
        raw_query['text'] = [args['text']]
    else:
        if 'name' in args:
            raw_query['name'] = [args['name']]
            # TODO: fix here
        if 'desc' in args:
            raw_query['desc'] = [args['desc']]
    if 'instructor' in args:
        raw_query['instructor'] = [args['instructor']]
    if 'courseid' in args:
        raw_query['courseid'] = [args['courseid']]
    if 'building' in args:
        raw_query['building'] = [args['building']]
    if 'room' in args:
        raw_query['room'] = [args['room']]
    # if 'datetime_str' in args:
    #     # Duplicated from get_courses_by_datetime()
    #     # TODO: combine code
    #     span_minutes = 0
    #     datetime_str = args['datetime_str']
    #     span_str = args.get('span_str')
    #     if span_str is not None:
    #         try:
    #             span_minutes = int(span_str)
    #             if not (config.course.SPAN_LOWER_LIMIT <= span_minutes <=
    #                     config.course.SPAN_UPPER_LIMIT):
    #                 raise(Exception(Message.SPAN_PARSE_FAIL))
    #             raw_query['timespan'] = [span_minutes]
    #         except:
    #             output = init_courses_output()
    #             output['response'] = {
    #                 'status': 400,
    #                 'error': {
    #                     'message': Message.SPAN_PARSE_FAIL
    #                 }
    #             }
    #             return output

    #     try:
    #         date_time = arrow.get(datetime_str)
    #         raw_query['datetime'] = [date_time]
    #     except:
    #         output = init_courses_output()
    #         output['response'] = {
    #             'status': 400,
    #             'error': {
    #                 'message': Message.DATETIME_PARSE_FAIL
    #             }
    #         }
    #         return output

    #     index = utils.get_course_index_from_date(date_time.datetime)
    #
    index = None
    if 'term' in args:
        # TODO: this is a quick hack to support the term arg
        index = 'current'

    searcher = CourseSearcher(raw_query, index=index, size=size)
    response = searcher.execute()
    output = format_courses_output(response)
    return output


def get_fce_by_id(courseid, size=100):
    searcher = FCESearcher({'courseid': [courseid]},
                           index=ES_FCE_INDEX,
                           size=size,
                           sort=['-year'])
    response = searcher.execute()
    output = format_fces_output(response)
    return output


def get_fce_by_instructor(instructor, size=100):
    searcher = FCESearcher({'instructor': [instructor]},
                           index=ES_FCE_INDEX,
                           size=size,
                           sort=['-year'])
    response = searcher.execute()
    output = format_fces_output(response)
    return output


def list_all_courses(term):
    if term == 'current':
        index = utils.get_current_course_index()
    else:
        index = ES_COURSE_INDEX_PREFIX + term
    print(index)
    query = Q()
    # Use ES api to search
    s = Search(index=index).query(query).extra(
            size=7000).source(False)

    try:
        response = s.execute().to_dict()
        if "hits" in response:
            for elem in response['hits']['hits']:
                print(elem['_id'])
            courseids = [elem['_id'] for elem in response['hits']['hits']]
            return courseids
    except:
        pass
    return []



if __name__ == '__main__':
    config.settings.DEBUG = True
    init_es_connection()

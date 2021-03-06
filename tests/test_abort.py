from tests import FlexGetBase


class TestAbort(FlexGetBase):

    __yaml__ = """
        feeds:
          test:
            # causes on_feed_abort to be called
            disable_builtins: yes

            # causes abort
            nzb_size: 10

            # another event hookup with this plugin
            headers:
              test: value
    """

    def test_abort(self):
        self.execute_feed('test')
        assert self.feed._abort, 'Feed not aborted'


import itertools
import logging
import warnings
import numpy as np

from copy import deepcopy
from datetime import datetime

from sklearn.svm.classes import SVR
from sklearn.ensemble import AdaBoostRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.ensemble import GradientBoostingRegressor
from early_stopping import Monitor

from xgboost import XGBRegressor


logging.getLogger("tensorflow").disabled = True
warnings.simplefilter(action='ignore', category=FutureWarning)

LOGGER = logging.getLogger('main.learner_configs')


class ConfigSpace:

    def __init__(self, Config, adict, pc):
        """
        :param Config: learner config class
        :param adict: a dictionary with learner parameters and value ranges
        :param pc: preprocessing config
        """
        self.Config = Config
        self.dim = "3d" if Config is ConfigLSTM else "2d"
        self.num_configs = 1
        self.parameter_ranges = adict
        self.pc = pc
        for k, v in self.parameter_ranges.items():
            setattr(self, k, v)
            self.num_configs *= len(v)
        LOGGER.info("Will evaluate %d configs" % self.num_configs)

    def generate_config(self):
        param_names, param_values = zip(*self.parameter_ranges.items())
        i = 0
        for x in itertools.product(*param_values):
            adict = dict(zip(param_names, x))
            yield self.Config(adict, self.pc)
            i += 1
            if i % 100 == 0:
                try:
                    LOGGER.info("%s: completed %d of %d" % (datetime.now(), i,
                                                            self.num_configs))
                except TypeError:
                    pass
        LOGGER.info("%s: completed %d of %d" % (datetime.now(),
                                        self.num_configs, self.num_configs))


class Config:

    def __init__(self, adict, pc):

        for k, v in adict.items():
            setattr(self, k, v)

        self.name = ", ".join(["%s: %s" % x for x in self.__dict__.items()])
        self.datetime = str(datetime.now())
        self.vals = adict
        self.learner = self.__class__.__name__.replace("Config", "")
        self.pc = pc

    def __str__(self):
        return self.name

    def forecast(self, model, testX):
        """Given a model, the first test instance, and the number of future
        steps to forecast, output a list with predictions, such that earlier
        predictions are used as input for later predictions.
        :param horizon: the number of steps ahead to forecast
        """
        lags = self.pc['lags']
        horizon = self.pc['horizon']
        result = []
        x = 0
        h = 0
        steps = len(testX)

        while x < steps:

            if h == horizon + 1 or x == 0:
                instance = testX[x].reshape(1, -1)
                buf = testX[x].tolist()[:lags]
                h = 0
            else:
                instance = np.array([np.concatenate(
                        [np.array(buf), testX[x][lags:]])])

            prediction = model.predict(instance)[0]
            pred_val = prediction

            if np.isnan(pred_val) or pred_val < -1.0 or pred_val > 1.0:
                warnings.warn("Error forecasting %s, setting forecast to 0.5"
                              % instance)
                pred_val = 0.5

            result.append(pred_val)
            buf.pop(0)
            buf.insert(lags-1, pred_val)
            x += 1
            h += 1

        return np.array(result)


class ConfigSVR(Config):

    kernel = None
    degree = None
    c = None
    eps = None

    def fit(self, x, y):
        model = SVR(kernel=self.kernel, degree=self.degree, C=self.c,
                    epsilon=self.eps)
        model.fit(x, y)
        return model


class ConfigAdaBoost(Config):

    n_estimators = None
    learning_rate = None
    loss = None

    def fit(self, x, y):
        model = AdaBoostRegressor(n_estimators=self.n_estimators,
            learning_rate=self.learning_rate, loss=self.loss,
            random_state=self.pc['random_state'])
        model.fit(x, y)
        return model


class ConfigRFR(Config):

    n_estimators = None
    max_features = None
    max_depth = None
    min_samples_split = None
    min_samples_leaf = None
    max_leaf_nodes = None

    def fit(self, x, y):
        model = RandomForestRegressor(n_estimators=self.n_estimators,
            max_features=self.max_features, max_depth=self.max_depth,
            min_samples_split=self.min_samples_split,
            min_samples_leaf=self.min_samples_leaf,
            max_leaf_nodes=self.max_leaf_nodes,
            random_state=self.pc['random_state'])
        model.fit(x, y)
        return model


class ConfigGB(Config):

    n_estimators = None
    learning_rate = None
    loss = None
    max_features = None
    max_depth = None
    min_samples_split = None
    min_samples_leaf = None
    max_leaf_nodes = None
    min_weight_fraction_leaf = None
    subsample = None
    alpha = None
    warm_start = None
    early_stopping = None

    def fit(self, trainX, trainY, valX, valY):
        model = GradientBoostingRegressor(n_estimators=self.n_estimators,
            learning_rate=self.learning_rate, loss=self.loss,
            max_features=self.max_features, max_depth=self.max_depth,
            min_samples_split=self.min_samples_split,
            min_samples_leaf=self.min_samples_leaf,
            max_leaf_nodes=self.max_leaf_nodes,
            min_weight_fraction_leaf=self.min_weight_fraction_leaf,
            subsample=self.subsample, alpha=self.alpha,
            warm_start=self.warm_start,
            random_state=self.pc['random_state'])
        model.fit(trainX, trainY,
            monitor=Monitor(valX.astype("float32"), valY.astype("float32"),
            max_consecutive_decreases=self.early_stopping))
        return model


class ConfigXGBoost(Config):

    max_depth = None
    learning_rate = None
    n_estimators = None
    objective = None
    booster = None
    n_jobs = None
    reg_alpha = None

    def fit(self, trainX, trainY):
        model = XGBRegressor(max_depth=self.max_depth,
            objective=self.objective, n_estimators=self.n_estimators,
            learning_rate=self.learning_rate, booster=self.booster,
            reg_alpha=self.reg_alpha, n_jobs=self.n_jobs,
            random_state=self.pc['random_state'])
        model.fit(trainX, trainY)
        return model


class ConfigLSTM(Config):

    bidirectional = None
    topology = []
    epochs = None
    batch_size = None
    activation = None
    dropout_rate = None
    optimizer = None
    kernel_regularizer = (0.0, 0.0)
    bias_regularization = (0.0, 0.0)
    early_stopping = None
    stateful = None

    def fit(self, trainX, trainY, valX, valY):
        """Importing Keras to be able to use it with multiprocessing
        """

        LOGGER.debug("Training LSTM ...")

        import numpy as np
        np.random.seed(self.pc['random_state'])

        from keras.models import Sequential
        from keras.layers import Dense, Dropout, Bidirectional  # , Activation
        from keras.layers.recurrent import LSTM
        from keras.callbacks import EarlyStopping, ModelCheckpoint
        from keras.regularizers import L1L2

        model = Sequential()

        kernel_regularizer = L1L2(l1=self.kernel_regularizer[0],
                           l2=self.kernel_regularizer[1])
        bias_regularizer = L1L2(l1=self.bias_regularization[0],
                           l2=self.bias_regularization[1])

        return_sequences_on_input = False if len(self.topology) == 2 else True

        # first layer
        if self.bidirectional:
            model.add(Bidirectional(LSTM(units=self.topology[0],
                           activation=self.activation,
                           return_sequences=return_sequences_on_input,
                           kernel_regularizer=kernel_regularizer,
                           bias_regularizer=bias_regularizer),
                           input_shape=(None, trainX.shape[2]),))
        else:
            model.add(LSTM(input_shape=(None, trainX.shape[2]),
                   units=self.topology[0],
                   activation=self.activation,
                   return_sequences=return_sequences_on_input,
                   kernel_regularizer=kernel_regularizer,
                   bias_regularizer=bias_regularizer))

        if self.dropout_rate:
            model.add(Dropout(self.dropout_rate))

        # other layers
        for n_layer in self.topology[1:-1]:
            if self.bidirectional:
                model.add(Bidirectional(LSTM(n_layer, return_sequences=False,
                           kernel_regularizer=kernel_regularizer,
                           bias_regularizer=bias_regularizer)))
            else:
                model.add(LSTM(n_layer, return_sequences=False,
                           kernel_regularizer=kernel_regularizer,
                           bias_regularizer=bias_regularizer))
            if self.dropout_rate:
                model.add(Dropout(self.dropout_rate))

        model.add(Dense(units=self.topology[-1]))

        model.compile(loss="mean_squared_error", optimizer=self.optimizer)

        # train
        if self.early_stopping:
            # early stopping: Keras to stop training when loss didn't improve
            # for `c.early_stopping` epochs
            early_stopping = EarlyStopping(monitor='val_loss',
                patience=self.early_stopping, verbose=0)
            model_check_point = ModelCheckpoint(
                filepath="logs/weights.{epoch:02d}-{val_loss:.2f}.hdf5",
                monitor='val_loss', save_best_only=True, verbose=0)
            callbacks = [early_stopping, model_check_point]
            model.fit(trainX, trainY, epochs=self.epochs,
                batch_size=self.batch_size, verbose=0,
                # validation_data=(valX, valY), callbacks=callbacks)
                validation_data=(trainX, trainY), callbacks=callbacks)
        else:
            model.fit(trainX, trainY, epochs=self.epochs,
                batch_size=self.batch_size, verbose=0,
                # validation_data=(valX, valY))
                validation_data=(trainX, trainY))

        LOGGER.debug("Trained LSTM.")

        return model

    def forecast(self, model, testX):
        """Given a Keras model, the first test instance, and the number of
        future steps to forecast, output a list with predictions, such that
        earlier redictions are used as input for later predictions.
        """
        lags = self.pc['lags']
        horizon = self.pc['horizon']
        result = []
        x = 0
        h = 0
        steps = len(testX)

        while x < steps:

            instance = deepcopy(testX[x])
            if h == horizon + 1 or x == 0:
                h = 0
                buf = testX[x][:, -1].tolist()
            else:
                instance[:, -1] = buf
            instance = np.array([instance])

            pred_val = model.predict(instance)[0][0]
            result.append(pred_val)
            buf.pop(0)
            buf.insert(lags-1, pred_val)
            x += 1
            h += 1

        return np.array(result)#.flatten()
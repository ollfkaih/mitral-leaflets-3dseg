import inspect as ispc
import monai.transforms as mtr
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.optim as optim
import torchmetrics

from metrics import MONAI_METRICS
from utils import LinearCosineLR



class EnhancedLightningModule(pl.LightningModule):
    def __init__(self, loss=nn.MSELoss(), optimizer={"name": "Adam", "params": {}},
                 lr_scheduler=True, final_activation=nn.Softmax(dim=1),
                 metrics=[]):
        super(EnhancedLightningModule, self).__init__()
        self.loss = loss
        self.optimizer_config = optimizer
        self.lr_scheduler = lr_scheduler
        self._init_metrics(metrics)
        self.post_process = None # Have to be initalize later
        self.final_activation = final_activation


    def _init_metrics(self, metrics):
        all_metrics = dict(ispc.getmembers(torchmetrics, ispc.isclass))
        all_metrics.update(MONAI_METRICS)
        # We use `nn.ModuleDict` to always be on proper device and such
        self.metrics = nn.ModuleDict({"mtrain": nn.ModuleDict(),
                                      "mval": nn.ModuleDict(),
                                      "mtest": nn.ModuleDict()})
        def build_metric(name, *args, **kwargs):
            return all_metrics[name](*args, **kwargs)
        for m in metrics:
            for mode in self.metrics.keys():
                if mode == "mtrain" and m["name"] in MONAI_METRICS.keys():
                    # Monai computes with `np.array` so use with parsimony
                    continue
                metric = build_metric(m["name"], *m.get("args", []), **m.get("kwargs", {}))
                display_name = f"v_{m['display_name']}" if mode == "mval" \
                               else m["display_name"]
                self.metrics[mode].update({display_name: metric})


    def _step(self, batch, batch_idx):
        if self.post_process is None:
            keep_labels = list(range(1, self.out_channels))
            #FIXME: Make this deactivable from config file
            # Don't process background
            self.post_process = mtr.FillHoles(keep_labels)
        x, y = batch
        out = self.forward(x)
        # Softmax is baked in `nn.CrossEntropyLoss`, only do it for preds
        sout = self.final_activation(out)
        preds = []
        for elt in sout: # Post process need to be done element wise
            preds.append(self.post_process(elt.squeeze()))
        preds = torch.stack(preds)
        return preds, self.loss(out, y)

    def _step_end(self, outs, name="loss", mode="train"):
        #errs = self.loss(outs["preds"], outs["target"])
        outs[name] = outs[name].mean()
        self._update_metrics(outs, mode)
        return outs


    def _update_metrics(self, outs, mode="train", log=True):
        # Not sure why but key "train" isn't allowed for an `nn.ModuleDict`
        #FIXME: Ever heard of `MetricCollection`?
        preds, y = outs["preds"], outs["target"]
        metrics = self.metrics[f"m{mode}"]
        on_step = True if mode == "test" else False
        for k, m in metrics.items():
            try:
                val = m(preds, y)
            except ValueError as err:
                # Some metrics need int to compute, e.g. Dice
                val = m(preds, y.to(torch.bool))
            #FIXME: Load by steps for test
            if val.numel() > 1:
                #FIXME: Quite an ugly patch
                idx = lambda i: i + 1 if k in ["v_hdf95", "v_masd"] else i
                self.log_dict({f"{k}/{idx(i)}": val[i] for i in range(len(val))},
                              on_epoch=True, on_step=on_step, sync_dist=True)
            else:
                self.log_dict({k: val}, on_epoch=True, on_step=on_step, sync_dist=True)

    def _log_errs(self, errs, name="loss", on_step=False):
        if isinstance(errs, dict): # Used in VAE for example
            if 'v' in name:
                errs = {f"v_{k}": v for k, v in errs.items()}
            self.log_dict(errs, prog_bar=True, on_step=on_step, on_epoch=True)
            return errs[name]
        self.log(name, errs, prog_bar=True, on_step=on_step, on_epoch=True,
                 sync_dist=True)
        return {name: errs}


    def training_step_end(self, outs):
        self._step_end(outs)

    def validation_step_end(self, outs):
        self._step_end(outs, "v_loss", "val")

    def test_step_end(self, outs):
        self._step_end(outs, mode="test")

    def training_step(self, batch, batch_idx):
        _, y = batch
        preds, errs = self._step(batch, batch_idx)
        outs = self._log_errs(errs, on_step=True)
        outs.update({"preds": preds, "target": y})
        return outs

    def validation_step(self, batch, batch_idx):
        _, y = batch
        preds, errs = self._step(batch, batch_idx)
        outs = self._log_errs(errs, name="v_loss")
        outs.update({"preds": preds, "target": y})
        return outs

    def test_step(self, batch, batch_idx):
        _, y = batch
        preds, errs = self._step(batch, batch_idx)
        outs = self._log_errs(errs)
        outs.update({"preds": preds, "target": y})
        return outs

    def predict_step(self, batch, batch_idx, dataloader_idx=None):
        #FIXME
        errs = self._step(batch, batch_idx)
        return self.preds


    def configure_optimizers(self):
        # All torch optimizer
        optims = dict(ispc.getmembers(optim, ispc.isclass))
        opt = optims[self.optimizer_config.pop("name")](self.parameters(),
                                                        **self.optimizer_config)

        if self.lr_scheduler:
            nb_batches = len(self.trainer._data_connector._train_dataloader_source.dataloader())
            tot_steps = self.trainer.max_epochs * nb_batches
            lr = opt.defaults["lr"]
            lrs = LinearCosineLR(opt, lr, 100, tot_steps)
        return [opt], [{"scheduler": lrs, "interval": "step"}]

    #def configure_callbacks(self):
    #    return pl.callbacks.ModelCheckpoint(monitor="v_loss")

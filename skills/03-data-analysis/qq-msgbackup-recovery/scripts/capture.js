rpc.exports.arm = function () {
    const mod = Process.getModuleByName('wrapper.node');
    const normalize = s => s.replace(/\\/g, '/').toLowerCase();
    if (normalize(mod.path) !== normalize(wrapperPath) || Process.arch !== 'x64')
        throw Error('Wrong process or wrapper');
    const response = mod.base.add(0x3d7b1f2);
    if (response.readU8() !== 0x55) throw Error('Unexpected callback entry');
    Interceptor.attach(response, {onEnter(args) {
        if (!args[1].readU8()) return;
        const vector = args[2], start = vector.readPointer();
        const length = vector.add(Process.pointerSize).readPointer().sub(start).toInt32();
        if (length === 16 || length === 32)
            send('backup-response', start.readByteArray(length));
    }});
};
